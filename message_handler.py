# message_handler.py
from telethon import TelegramClient, events
import os
import re
import logging
import traceback
from typing import Optional, BinaryIO, Dict, List, Any, Tuple
from tempfile import NamedTemporaryFile
import asyncio
from datetime import datetime, timedelta, time
from telegram import error as telegram_error
from locales import get_text

class MyMessageHandler:
    def __init__(self, db, client: TelegramClient, bot):
        self.db = db
        self.client = client
        self.bot = bot
        # 用于跟踪临时文件
        self.temp_files = {}
        # 启动清理任务
        self.cleanup_task = None
        # 媒体缓存
        self.media_cache = {}
        # 已处理的媒体组
        self.processed_media_groups = set()

    async def start_cleanup_task(self):
        """启动定期清理任务"""
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self.cleanup_old_files())

    async def cleanup_old_files(self):
        """定期清理过期的临时文件"""
        while True:
            try:
                current_time = datetime.now()
                files_to_remove = []

                # 检查所有临时文件
                for file_path, timestamp in list(self.temp_files.items()):
                    if current_time - timestamp > timedelta(hours=1):  # 1小时后清理
                        if os.path.exists(file_path):
                            try:
                                os.remove(file_path)
                                logging.info(get_text('en', 'file_cleanup_success', file_path=file_path))
                            except Exception as e:
                                logging.error(get_text('en', 'file_cleanup_error', file_path=file_path, error=str(e)))
                        files_to_remove.append(file_path)

                # 从跟踪列表中移除已清理的文件
                for file_path in files_to_remove:
                    self.temp_files.pop(file_path, None)

                # 清理媒体缓存
                media_ids_to_remove = []
                for media_id, media_info in list(self.media_cache.items()):
                    if current_time - media_info.get('timestamp', current_time) > timedelta(minutes=10):  # 10分钟后清理
                        media_ids_to_remove.append(media_id)

                # 从缓存中移除过期的媒体
                for media_id in media_ids_to_remove:
                    self.media_cache.pop(media_id, None)

                # 清理已处理的媒体组
                self.processed_media_groups.clear()

            except Exception as e:
                logging.error(get_text('en', 'cleanup_task_error', error=str(e)))

            # 每小时运行一次
            await asyncio.sleep(3600)

    async def clear_media_cache(self, media_id, delay_seconds=600):
        """延迟清理媒体缓存"""
        await asyncio.sleep(delay_seconds)
        if media_id in self.media_cache:
            self.media_cache.pop(media_id, None)
            logging.info(f"媒体缓存已清理: {media_id}")

    def get_media_id(self, message) -> str:
        """获取媒体文件的唯一标识"""
        try:
            # 尝试不同的属性来生成唯一ID
            if hasattr(message.media, 'photo'):
                photo = message.media.photo
                return f"photo_{photo.id}_{photo.access_hash}"
            elif hasattr(message.media, 'document'):
                doc = message.media.document
                return f"document_{doc.id}_{doc.access_hash}"
            elif hasattr(message.media, 'video'):
                video = message.media.video
                return f"video_{video.id}_{video.access_hash}"
            else:
                # 如果无法获取特定属性，使用消息的唯一标识
                return f"media_{message.chat_id}_{message.id}"
        except Exception as e:
            logging.error(f"获取媒体ID时出错: {str(e)}")
            # 如果出错，使用消息的唯一标识
            return f"media_{message.chat_id}_{message.id}"

    def get_media_type(self, message) -> str:
        """获取媒体类型"""
        if hasattr(message.media, 'photo'):
            return 'photo'
        elif hasattr(message.media, 'document'):
            # 检查是否是贴图
            if hasattr(message.media.document, 'attributes'):
                for attr in message.media.document.attributes:
                    if hasattr(attr, 'CONSTRUCTOR_ID') and attr.CONSTRUCTOR_ID == 0x6319d612:  # DocumentAttributeSticker
                        return 'sticker'
                    elif hasattr(attr, '__class__') and 'DocumentAttributeSticker' in str(attr.__class__):
                        return 'sticker'
            return 'document'
        elif hasattr(message.media, 'video'):
            return 'video'
        else:
            return 'unknown'

    async def handle_channel_message(self, event):
        """处理频道消息"""
        try:
            message = event.message
            if not message:
                return

            chat = await event.get_chat()
            channel_info = self.db.get_channel_info(chat.id)

            if not channel_info or not channel_info.get('is_active'):
                return

            # 获取所有转发频道
            forward_channels = self.db.get_all_forward_channels(chat.id)
            if not forward_channels:
                return

            # 获取消息内容用于过滤
            content = ""
            if getattr(message, 'text', None):
                content = message.text
            elif getattr(message, 'caption', None):
                content = message.caption

            # 获取当前时间
            current_time = datetime.now()
            current_time_str = current_time.strftime('%H:%M')
            current_weekday = current_time.weekday() + 1  # 周一为1，周日为7

            for channel in forward_channels:
                try:
                    monitor_id = chat.id
                    forward_id = channel.get('channel_id')

                    # 检查时间段过滤
                    if not self.check_time_filter(monitor_id, forward_id, current_time_str, current_weekday):
                        logging.info(f"消息被时间段过滤器拦截: 监控频道={monitor_id}, 转发频道={forward_id}")
                        continue

                    # 检查内容过滤
                    if content and not self.check_content_filter(monitor_id, forward_id, content):
                        logging.info(f"消息被内容过滤器拦截: 监控频道={monitor_id}, 转发频道={forward_id}")
                        continue

                    # 通过所有过滤器，转发消息
                    await self.handle_forward_message(message, chat, channel)
                except Exception as e:
                    logging.error(get_text('en', 'forward_channel_error',
                                         channel_id=channel.get('channel_id'),
                                         error=str(e)))
                    continue
        except Exception as e:
            logging.error(get_text('en', 'message_handler_error', error=str(e)))
            logging.error(get_text('en', 'error_details', details=traceback.format_exc()))

    def check_time_filter(self, monitor_id: int, forward_id: int, current_time: str, current_weekday: int) -> bool:
        """检查时间段过滤器"""
        try:
            # 获取时间段过滤器
            time_filters = self.db.get_time_filters(monitor_id, forward_id)

            # 如果没有过滤器，允许所有时间
            if not time_filters:
                return True

            # 检查每个时间段过滤器
            for filter_rule in time_filters:
                # 检查当前星期是否在过滤器的星期范围内
                days_of_week = filter_rule.get('days_of_week', '').split(',')
                if days_of_week and str(current_weekday) not in days_of_week:
                    continue

                # 检查当前时间是否在过滤器的时间范围内
                start_time = filter_rule.get('start_time')
                end_time = filter_rule.get('end_time')

                if start_time and end_time:
                    # 如果当前时间在范围内
                    in_time_range = start_time <= current_time <= end_time

                    # 根据模式决定是否允许
                    mode = filter_rule.get('mode', 'ALLOW')
                    if mode == 'ALLOW' and in_time_range:
                        return True
                    elif mode == 'BLOCK' and in_time_range:
                        return False

            # 如果没有匹配的规则，默认允许
            return True

        except Exception as e:
            logging.error(f"检查时间段过滤器时出错: {e}")
            # 出错时默认允许
            return True

    def check_content_filter(self, monitor_id: int, forward_id: int, content: str) -> bool:
        """检查内容过滤器"""
        try:
            # 获取过滤规则
            filter_rules = self.db.get_filter_rules(monitor_id, forward_id)

            # 如果没有规则，允许所有内容
            if not filter_rules:
                return True

            # 分类规则
            whitelist_rules = []
            blacklist_rules = []

            for rule in filter_rules:
                if rule.get('rule_type') == 'WHITELIST':
                    whitelist_rules.append(rule)
                elif rule.get('rule_type') == 'BLACKLIST':
                    blacklist_rules.append(rule)

            # 如果有白名单规则，必须匹配至少一条才允许
            if whitelist_rules:
                whitelist_match = False
                for rule in whitelist_rules:
                    if self.match_rule(rule, content):
                        whitelist_match = True
                        break

                if not whitelist_match:
                    return False

            # 如果有黑名单规则，匹配任一条则拒绝
            for rule in blacklist_rules:
                if self.match_rule(rule, content):
                    return False

            # 通过所有过滤
            return True

        except Exception as e:
            logging.error(f"检查内容过滤器时出错: {e}")
            # 出错时默认允许
            return True

    def match_rule(self, rule: dict, content: str) -> bool:
        """检查内容是否匹配规则"""
        try:
            pattern = rule.get('pattern', '')
            if not pattern:
                return False

            filter_mode = rule.get('filter_mode', 'KEYWORD')

            if filter_mode == 'KEYWORD':
                # 关键词模式，简单字符串包含
                return pattern.lower() in content.lower()
            elif filter_mode == 'REGEX':
                # 正则表达式模式
                return bool(re.search(pattern, content, re.IGNORECASE))

            return False

        except Exception as e:
            logging.error(f"匹配规则时出错: {e}")
            return False

    async def handle_media_send(self, message, channel_id, media_type: str = None, reply_to_message_id: int = None, from_chat = None):
        """处理媒体发送并确保清理"""
        # 下载媒体文件
        media_info = await self.download_media_file(message, media_type)
        if not media_info:
            logging.error("媒体文件下载失败")
            return

        file_path = media_info.get('file_path')
        media_type = media_info.get('media_type')

        try:
            # 只有在没有回复消息时才添加说明文字
            caption = None
            if not reply_to_message_id and from_chat:
                # 构建用户名部分
                username = f"(@{from_chat.username})" if getattr(from_chat, 'username', None) else ""

                # 使用简化的模板作为媒体文件的标题
                caption = f"📨 转发自 {getattr(from_chat, 'title', 'Unknown Channel')} {username}"
            elif message.text or message.caption:
                caption = message.text or message.caption

            # 发送文件
            with open(file_path, 'rb') as media_file:
                try:
                    file_data = media_file.read()
                    send_kwargs = {
                        'chat_id': channel_id,
                        'caption': caption,
                        'read_timeout': 1800,
                        'write_timeout': 1800
                    }

                    if reply_to_message_id:
                        send_kwargs['reply_to_message_id'] = reply_to_message_id

                    if media_type == 'photo':
                        send_kwargs['photo'] = file_data
                        await self.bot.send_photo(**send_kwargs)
                    elif media_type == 'video':
                        send_kwargs.update({
                            'video': file_data,
                            'supports_streaming': True
                        })

                        # 添加视频参数
                        if 'width' in media_info:
                            send_kwargs['width'] = media_info['width']
                        if 'height' in media_info:
                            send_kwargs['height'] = media_info['height']
                        if 'duration' in media_info:
                            send_kwargs['duration'] = media_info['duration']

                        # 如果有缩略图
                        if 'thumb_path' in media_info and os.path.exists(media_info['thumb_path']):
                            with open(media_info['thumb_path'], 'rb') as thumb_file:
                                send_kwargs['thumb'] = thumb_file.read()

                        await self.bot.send_video(**send_kwargs)

                        # 清理缩略图
                        if 'thumb_path' in media_info and os.path.exists(media_info['thumb_path']):
                            os.remove(media_info['thumb_path'])

                    elif media_type == 'document':
                        send_kwargs['document'] = file_data
                        if 'filename' in media_info:
                            send_kwargs['filename'] = media_info['filename']
                        await self.bot.send_document(**send_kwargs)
                    elif media_type == 'sticker':
                        # 发送贴图
                        await self.bot.send_sticker(
                            chat_id=channel_id,
                            sticker=file_data,
                            reply_to_message_id=reply_to_message_id
                        )

                    logging.info(f"文件发送成功: {media_type}" +
                           (f" (回复到消息: {reply_to_message_id})" if reply_to_message_id else ""))
                finally:
                    del file_data  # 释放内存

            # 发送成功后清理文件
            await self.cleanup_file(file_path)
            return True

        except Exception as e:
            logging.error(f"处理媒体文件时出错: {str(e)}")
            if file_path:
                await self.cleanup_file(file_path)
            return False

    async def handle_forward_message(self, message, from_chat, to_channel):
        """处理消息转发"""
        if not message or not from_chat or not to_channel:
            logging.error(get_text('en', 'missing_parameters'))
            return

        try:
            channel_id = to_channel.get('channel_id')
            if not channel_id:
                logging.error(get_text('en', 'invalid_channel_id'))
                return

            try:
                # 检查频道ID是否已经包含-100前缀
                channel_id_str = str(channel_id)
                if channel_id_str.startswith('-100'):
                    channel_id = int(channel_id_str)
                else:
                    channel_id = int("-100" + channel_id_str)
            except ValueError as e:
                logging.error(f"频道ID格式错误: {channel_id}, 错误: {e}")
                return

            # 检查是否是回复消息
            reply_to_message_id = None
            original_reply_message = None

            if hasattr(message, 'reply_to_msg_id') and message.reply_to_msg_id:
                try:
                    # 获取原始回复消息
                    original_reply_message = await self.client.get_messages(from_chat.id, ids=message.reply_to_msg_id)

                    # 在数据库中查找这条消息是否已经转发过
                    forwarded_reply = self.db.get_forwarded_message(from_chat.id, message.reply_to_msg_id, channel_id)
                    if forwarded_reply:
                        # 如果找到了转发的回复消息，使用其ID作为回复ID
                        reply_to_message_id = forwarded_reply['forwarded_message_id']
                        logging.info(f"找到原始回复消息的转发记录，将使用原生回复: {reply_to_message_id}")
                except Exception as e:
                    logging.warning(f"获取原始回复消息失败: {e}")

            forwarded_msg = None

            # 尝试直接转发
            try:
                # 如果有原生回复消息的ID，使用原生回复
                if reply_to_message_id:
                    forwarded_msg = await self.bot.copy_message(
                        chat_id=channel_id,
                        from_chat_id=from_chat.id,
                        message_id=message.id,
                        reply_to_message_id=reply_to_message_id
                    )
                    # 保存转发关系
                    self.db.save_forwarded_message(from_chat.id, message.id, channel_id, forwarded_msg.message_id)
                    logging.info(f"使用原生回复成功转发消息到 {channel_id}")
                    return
                else:
                    # 尝试直接转发
                    forwarded_msg = await self.bot.forward_message(
                        chat_id=channel_id,
                        from_chat_id=from_chat.id,
                        message_id=message.id
                    )
                    # 保存转发关系
                    self.db.save_forwarded_message(from_chat.id, message.id, channel_id, forwarded_msg.message_id)
                    logging.info(get_text('en', 'forward_success', channel_id=channel_id))
                    return
            except telegram_error.BadRequest as e:
                if "Chat not found" in str(e):
                    logging.error(f"频道 {channel_id} 不存在或机器人无法访问，请检查权限或频道ID")
                    return
                else:
                    logging.warning(get_text('en', 'direct_forward_failed', error=str(e)))
            except Exception as e:
                logging.warning(get_text('en', 'direct_forward_failed', error=str(e)))

            # 如果直接转发失败，处理文本消息
            if getattr(message, 'text', None) or getattr(message, 'caption', None):
                content = message.text or message.caption
                # 获取频道类型
                chat_type_key = 'chat_type_channel'  # 默认类型
                if hasattr(from_chat, 'type'):
                    if from_chat.type == 'channel':
                        if getattr(from_chat, 'username', None):
                            chat_type_key = 'chat_type_public_channel'
                        else:
                            chat_type_key = 'chat_type_private_channel'
                    elif from_chat.type == 'group':
                        chat_type_key = 'chat_type_group'
                    elif from_chat.type == 'supergroup':
                        chat_type_key = 'chat_type_supergroup'
                    elif from_chat.type == 'gigagroup':
                        chat_type_key = 'chat_type_gigagroup'

                # 获取用户语言
                lang = self.db.get_user_language(to_channel.get('channel_id', 0)) or 'en'

                # 获取频道类型显示文本
                chat_type = get_text(lang, chat_type_key)

                # 获取当前时间
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # 构建用户名部分
                username = f"(@{from_chat.username})" if getattr(from_chat, 'username', None) else ""

                # 检查是否是回复消息
                reply_text = ""
                if hasattr(message, 'reply_to_msg_id') and message.reply_to_msg_id and not reply_to_message_id:
                    try:
                        # 尝试获取原始回复消息
                        reply_msg = await self.client.get_messages(from_chat.id, ids=message.reply_to_msg_id)
                        if reply_msg and (reply_msg.text or reply_msg.caption):
                            reply_content = reply_msg.text or reply_msg.caption
                            # 截取回复消息的前50个字符
                            short_reply = reply_content[:50] + "..." if len(reply_content) > 50 else reply_content
                            reply_text = get_text(lang, 'reply_to_message', text=short_reply) + "\n"
                    except Exception as e:
                        logging.warning(f"获取回复消息失败: {e}")

                # 使用新的消息模板
                forwarded_text = get_text(lang, 'forwarded_message_template',
                                         title=getattr(from_chat, 'title', 'Unknown Channel'),
                                         username=username,
                                         chat_type=chat_type,
                                         time=current_time,
                                         content=reply_text + content)

                # 检查是否有自定义表情
                await self.handle_custom_emoji(message, channel_id)

                # 发送文本消息，支持Markdown格式
                try:
                    # 如果有原生回复消息的ID，使用原生回复
                    send_kwargs = {
                        'chat_id': channel_id,
                        'text': forwarded_text,
                        'parse_mode': 'Markdown',
                        'disable_web_page_preview': True
                    }

                    if reply_to_message_id:
                        send_kwargs['reply_to_message_id'] = reply_to_message_id

                    forwarded_msg = await self.bot.send_message(**send_kwargs)

                    # 保存转发关系
                    self.db.save_forwarded_message(from_chat.id, message.id, channel_id, forwarded_msg.message_id)

                except Exception as e:
                    # 如果Markdown解析失败，尝试使用纯文本
                    logging.warning(f"使用Markdown发送消息失败: {e}")
                    send_kwargs = {
                        'chat_id': channel_id,
                        'text': forwarded_text,
                        'parse_mode': None,
                        'disable_web_page_preview': True
                    }

                    if reply_to_message_id:
                        send_kwargs['reply_to_message_id'] = reply_to_message_id

                    forwarded_msg = await self.bot.send_message(**send_kwargs)

                    # 保存转发关系
                    self.db.save_forwarded_message(from_chat.id, message.id, channel_id, forwarded_msg.message_id)

                logging.info(get_text('en', 'text_send_success', channel_id=channel_id))

            # 异步处理媒体消息
            if getattr(message, 'media', None) and forwarded_msg:

                # 检查是否是媒体组
                if hasattr(message, 'grouped_id') and message.grouped_id:
                    # 异步处理媒体组
                    asyncio.create_task(self.handle_media_group(
                        message=message,
                        channel_id=channel_id,
                        reply_to_message_id=forwarded_msg.message_id
                    ))
                    return

                # 确定媒体类型
                media_type = self.get_media_type(message)

                # 如果是贴图，使用特殊处理
                if media_type == 'sticker':
                    asyncio.create_task(self.handle_sticker_send(
                        message=message,
                        channel_id=channel_id,
                        from_chat=from_chat,
                        reply_to_message_id=forwarded_msg.message_id
                    ))
                    return

                # 异步处理媒体文件
                asyncio.create_task(self.handle_media_send(
                    message=message,
                    channel_id=channel_id,
                    media_type=media_type,
                    reply_to_message_id=forwarded_msg.message_id,
                    from_chat=from_chat
                ))
        except Exception as e:
            logging.error(get_text('en', 'forward_message_error', error=str(e)))
            logging.error(get_text('en', 'error_details', details=traceback.format_exc()))
            raise

    async def cleanup_file(self, file_path: str):
        """清理单个文件"""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                self.temp_files.pop(file_path, None)
                logging.info(get_text('en', 'file_cleanup_success', file_path=file_path))
        except Exception as e:
            logging.error(get_text('en', 'file_cleanup_error',
                                 file_path=file_path,
                                 error=str(e)))

    async def download_progress_callback(self, current, total):
        """下载进度回调"""
        if total:
            percentage = current * 100 / total
            if percentage % 20 == 0:  # 每20%记录一次
                logging.info(get_text('en', 'download_progress', percentage=percentage))

    async def handle_edited_message(self, event):
        """处理消息编辑事件"""
        try:
            # 获取编辑后的消息
            message = event.message
            if not message:
                return

            # 获取频道信息
            chat = await event.get_chat()
            channel_info = self.db.get_channel_info(chat.id)

            if not channel_info or not channel_info.get('is_active'):
                return

            # 获取所有转发频道
            forward_channels = self.db.get_all_forward_channels(chat.id)
            if not forward_channels:
                return

            # 获取消息内容
            content = message.text or message.caption or ""
            if not content:
                return

            # 获取用户语言
            lang = self.db.get_user_language(chat.id) or 'en'

            # 构建编辑通知消息
            edit_notice = get_text(lang, 'edited_message')
            edit_text = f"{edit_notice}\n\n{content}"

            # 向所有转发频道发送编辑通知
            for channel in forward_channels:
                try:
                    # 检查频道ID是否已经包含-100前缀
                    channel_id_str = str(channel.get('channel_id'))
                    if channel_id_str.startswith('-100'):
                        channel_id = int(channel_id_str)
                    else:
                        channel_id = int("-100" + channel_id_str)

                    # 以回复形式发送编辑通知
                    # 注意：这里我们不尝试编辑原消息，而是发送新消息作为通知
                    await self.bot.send_message(
                        chat_id=channel_id,
                        text=edit_text,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )

                except Exception as e:
                    logging.error(f"发送编辑通知到频道 {channel.get('channel_id')} 失败: {str(e)}")
                    continue

        except Exception as e:
            logging.error(f"处理消息编辑事件时出错: {str(e)}")
            logging.error(f"错误详情: {traceback.format_exc()}")

    async def handle_deleted_message(self, event):
        """处理消息删除事件"""
        try:
            # 注意：删除的消息事件只包含消息ID，不包含内容
            # 我们需要从事件中获取频道ID和消息ID

            # 获取频道ID
            chat_id = event.chat_id
            if not chat_id:
                return

            # 获取频道信息
            channel_info = self.db.get_channel_info(chat_id)
            if not channel_info or not channel_info.get('is_active'):
                return

            # 获取所有转发频道
            forward_channels = self.db.get_all_forward_channels(chat_id)
            if not forward_channels:
                return

            # 获取用户语言
            lang = self.db.get_user_language(chat_id) or 'en'

            # 构建删除通知消息
            delete_notice = get_text(lang, 'deleted_message')

            # 向所有转发频道发送删除通知
            for channel in forward_channels:
                try:
                    # 检查频道ID是否已经包含-100前缀
                    channel_id_str = str(channel.get('channel_id'))
                    if channel_id_str.startswith('-100'):
                        channel_id = int(channel_id_str)
                    else:
                        channel_id = int("-100" + channel_id_str)

                    # 发送删除通知
                    await self.bot.send_message(
                        chat_id=channel_id,
                        text=delete_notice,
                        parse_mode='Markdown'
                    )

                except Exception as e:
                    logging.error(f"发送删除通知到频道 {channel.get('channel_id')} 失败: {str(e)}")
                    continue

        except Exception as e:
            logging.error(f"处理消息删除事件时出错: {str(e)}")
            logging.error(f"错误详情: {traceback.format_exc()}")

    async def download_media_file(self, message, media_type: str = None) -> dict:
        """下载媒体文件并返回相关信息"""
        # 如果没有指定媒体类型，自动检测
        if media_type is None:
            media_type = self.get_media_type(message)

        # 生成媒体ID
        media_id = self.get_media_id(message)

        # 检查缓存
        if media_id in self.media_cache:
            logging.info(f"使用缓存的媒体文件: {media_id}")
            return self.media_cache[media_id]

        tmp = None
        file_path = None
        chunk_size = 20 * 1024 * 1024  # 20MB 分块

        try:
            # 获取文件大小
            file_size = getattr(message.media, 'file_size', 0) or getattr(message.media, 'size', 0)
            logging.info(f"开始下载媒体文件，大小: {file_size / (1024*1024):.2f}MB")

            # 创建临时文件
            tmp = NamedTemporaryFile(delete=False, prefix='tg_', suffix=f'.{media_type}')
            file_path = tmp.name

            # 使用分块下载
            downloaded_size = 0
            async for chunk in self.client.iter_download(message.media, chunk_size=chunk_size):
                if chunk:
                    tmp.write(chunk)
                    downloaded_size += len(chunk)
                    if downloaded_size % (50 * 1024 * 1024) == 0:
                        progress = (downloaded_size / file_size) * 100 if file_size else 0
                        logging.info(f"下载进度: {progress:.1f}% ({downloaded_size/(1024*1024):.1f}MB/{file_size/(1024*1024):.1f}MB)")

                    if downloaded_size % (100 * 1024 * 1024) == 0:
                        tmp.flush()
                        os.fsync(tmp.fileno())

            tmp.close()
            logging.info("媒体文件下载完成")

            if not os.path.exists(file_path):
                raise Exception(get_text('en', 'downloaded_file_not_found', file_path=file_path))

            # 记录临时文件
            self.temp_files[file_path] = datetime.now()

            # 收集媒体信息
            media_info = {
                'file_path': file_path,
                'file_size': file_size,
                'media_type': media_type,
                'timestamp': datetime.now()
            }

            # 收集特定媒体类型的额外信息
            if media_type == 'video' and hasattr(message.media, 'video'):
                video = message.media.video
                if hasattr(video, 'width'):
                    media_info['width'] = video.width
                if hasattr(video, 'height'):
                    media_info['height'] = video.height
                if hasattr(video, 'duration'):
                    media_info['duration'] = video.duration

                # 如果有缩略图
                if hasattr(video, 'thumb') and video.thumb:
                    try:
                        thumb_path = await self.client.download_media(video.thumb)
                        media_info['thumb_path'] = thumb_path
                    except Exception as e:
                        logging.warning(f"无法下载视频缩略图: {str(e)}")

            # 如果是文档，获取文件名
            elif media_type == 'document' and hasattr(message.media, 'document'):
                if hasattr(message.media.document, 'attributes'):
                    for attr in message.media.document.attributes:
                        if hasattr(attr, 'file_name'):
                            media_info['filename'] = attr.file_name
                            break

            # 将结果存入缓存
            self.media_cache[media_id] = media_info

            # 设置缓存过期时间（例妈10分钟后自动清理）
            asyncio.create_task(self.clear_media_cache(media_id, 600))

            return media_info

        except Exception as e:
            logging.error(f"下载媒体文件时出错: {str(e)}")
            if file_path and file_path in self.temp_files:
                await self.cleanup_file(file_path)
            return None

    async def handle_media_group(self, message, channel_id, reply_to_message_id=None):
        """处理媒体组（多张图片或视频）"""
        try:
            # 获取媒体组ID
            group_id = getattr(message, 'grouped_id', None)
            if not group_id:
                # 如果不是媒体组，使用普通媒体处理
                media_type = self.get_media_type(message)
                await self.handle_media_send(message, channel_id, media_type, reply_to_message_id=reply_to_message_id)
                return

            # 检查是否已经处理过这个媒体组
            if group_id in self.processed_media_groups:
                logging.info(f"媒体组 {group_id} 已经处理过，跳过")
                return

            # 标记为已处理
            self.processed_media_groups.add(group_id)

            # 获取同一组的所有媒体消息
            media_messages = await self.client.get_messages(
                message.chat_id,
                limit=10,  # 合理的限制
                offset_id=message.id,
                reverse=True
            )

            # 过滤出同一组的媒体
            group_media = [msg for msg in media_messages if hasattr(msg, 'grouped_id') and msg.grouped_id == group_id]

            # 准备媒体列表
            media_list = []
            for msg in group_media:
                media_type = self.get_media_type(msg)
                media_info = await self.download_media_file(msg, media_type)
                if media_info:
                    media_list.append({
                        'type': media_type,
                        'path': media_info['file_path'],
                        'caption': msg.text or msg.caption,
                        'media_info': media_info
                    })

            # 发送媒体组
            if media_list:
                await self.send_media_group(channel_id, media_list, reply_to_message_id)

        except Exception as e:
            logging.error(f"处理媒体组时出错: {str(e)}")
            logging.error(traceback.format_exc())

    async def send_media_group(self, channel_id, media_list, reply_to_message_id=None):
        """发送媒体组"""
        try:
            # 如果只有一个媒体文件，使用单个发送
            if len(media_list) == 1:
                media = media_list[0]
                with open(media['path'], 'rb') as media_file:
                    file_data = media_file.read()
                    send_kwargs = {
                        'chat_id': channel_id,
                        'caption': media['caption'],
                        'read_timeout': 1800,
                        'write_timeout': 1800
                    }

                    if reply_to_message_id:
                        send_kwargs['reply_to_message_id'] = reply_to_message_id

                    if media['type'] == 'photo':
                        send_kwargs['photo'] = file_data
                        await self.bot.send_photo(**send_kwargs)
                    elif media['type'] == 'video':
                        send_kwargs['video'] = file_data
                        send_kwargs['supports_streaming'] = True

                        # 添加视频参数
                        media_info = media['media_info']
                        if 'width' in media_info:
                            send_kwargs['width'] = media_info['width']
                        if 'height' in media_info:
                            send_kwargs['height'] = media_info['height']
                        if 'duration' in media_info:
                            send_kwargs['duration'] = media_info['duration']

                        await self.bot.send_video(**send_kwargs)
                    elif media['type'] == 'document':
                        send_kwargs['document'] = file_data
                        if 'filename' in media['media_info']:
                            send_kwargs['filename'] = media['media_info']['filename']
                        await self.bot.send_document(**send_kwargs)

            # 如果有多个媒体文件，使用媒体组发送
            else:
                # 准备媒体输入列表
                input_media = []
                for i, media in enumerate(media_list):
                    with open(media['path'], 'rb') as media_file:
                        file_data = media_file.read()
                        media_dict = {
                            'type': media['type'],
                            'media': file_data,
                            'caption': media['caption'] if i == 0 else None  # 只在第一个媒体上显示标题
                        }
                        input_media.append(media_dict)

                # 发送媒体组
                await self.bot.send_media_group(
                    chat_id=channel_id,
                    media=input_media,
                    reply_to_message_id=reply_to_message_id,
                    read_timeout=1800,
                    write_timeout=1800
                )

            # 清理媒体文件
            for media in media_list:
                await self.cleanup_file(media['path'])

            logging.info(f"媒体组发送成功，共 {len(media_list)} 个文件")

        except Exception as e:
            logging.error(f"发送媒体组时出错: {str(e)}")
            logging.error(traceback.format_exc())

            # 如果失败，尝试逐个发送
            try:
                for media in media_list:
                    with open(media['path'], 'rb') as media_file:
                        file_data = media_file.read()
                        send_kwargs = {
                            'chat_id': channel_id,
                            'caption': media['caption'],
                            'reply_to_message_id': reply_to_message_id,
                            'read_timeout': 1800,
                            'write_timeout': 1800
                        }

                        if media['type'] == 'photo':
                            send_kwargs['photo'] = file_data
                            await self.bot.send_photo(**send_kwargs)
                        elif media['type'] == 'video':
                            send_kwargs['video'] = file_data
                            await self.bot.send_video(**send_kwargs)
                        elif media['type'] == 'document':
                            send_kwargs['document'] = file_data
                            await self.bot.send_document(**send_kwargs)

                    # 清理媒体文件
                    await self.cleanup_file(media['path'])

            except Exception as e2:
                logging.error(f"备用方法发送媒体失败: {str(e2)}")
                # 清理媒体文件
                for media in media_list:
                    await self.cleanup_file(media['path'])

    async def handle_sticker_send(self, message, channel_id, from_chat, reply_to_message_id=None):
        """处理贴图发送"""
        try:
            logging.info(f"开始处理贴图发送")

            # 下载贴图文件
            sticker_path = await self.client.download_media(message.media)
            logging.info(f"贴图下载完成: {sticker_path}")

            # 构建用户名部分
            username = f"(@{from_chat.username})" if getattr(from_chat, 'username', None) else ""

            # 使用简化的模板作为贴图标题
            caption = f"📨 转发自 {getattr(from_chat, 'title', 'Unknown Channel')} {username}"

            # 发送贴图
            with open(sticker_path, 'rb') as sticker_file:
                await self.bot.send_sticker(
                    chat_id=channel_id,
                    sticker=sticker_file.read(),
                    reply_to_message_id=reply_to_message_id
                )

                # 如果有标题且没有回复消息，发送标题
                if caption and not reply_to_message_id:
                    await self.bot.send_message(
                        chat_id=channel_id,
                        text=caption,
                        disable_web_page_preview=True
                    )

            # 清理临时文件
            if sticker_path and os.path.exists(sticker_path):
                os.remove(sticker_path)
                logging.info(f"贴图文件已清理: {sticker_path}")

            logging.info(f"贴图发送成功")

        except Exception as e:
            logging.error(f"发送贴图时出错: {str(e)}")
            logging.error(f"错误详情: {traceback.format_exc()}")

            # 如果失败，发送错误消息
            try:
                await self.bot.send_message(
                    chat_id=channel_id,
                    text=f"⚠️ 贴图发送失败: {str(e)}",
                    reply_to_message_id=reply_to_message_id
                )
            except Exception as e2:
                logging.error(f"发送错误消息失败: {str(e2)}")

            # 清理临时文件
            if 'sticker_path' in locals() and sticker_path and os.path.exists(sticker_path):
                try:
                    os.remove(sticker_path)
                except Exception as e3:
                    logging.error(f"清理贴图文件失败: {str(e3)}")

    async def handle_custom_emoji(self, message, channel_id):
        """处理自定义表情"""
        try:
            # 检查消息中的自定义表情实体
            has_custom_emoji = False

            # 检查 entities 属性
            if hasattr(message, 'entities') and message.entities:
                for entity in message.entities:
                    if hasattr(entity, 'CONSTRUCTOR_ID') and entity.CONSTRUCTOR_ID == 0x81ccf4d:  # MessageEntityCustomEmoji
                        has_custom_emoji = True
                        break
                    elif hasattr(entity, '__class__') and 'MessageEntityCustomEmoji' in str(entity.__class__):
                        has_custom_emoji = True
                        break

            # 检查 caption_entities 属性
            if not has_custom_emoji and hasattr(message, 'caption_entities') and message.caption_entities:
                for entity in message.caption_entities:
                    if hasattr(entity, 'CONSTRUCTOR_ID') and entity.CONSTRUCTOR_ID == 0x81ccf4d:  # MessageEntityCustomEmoji
                        has_custom_emoji = True
                        break
                    elif hasattr(entity, '__class__') and 'MessageEntityCustomEmoji' in str(entity.__class__):
                        has_custom_emoji = True
                        break

            if has_custom_emoji:
                logging.info(f"检测到自定义表情，添加提示消息")
                await self.bot.send_message(
                    chat_id=channel_id,
                    text="ℹ️ 原消息包含自定义表情，可能无法完全显示。"
                )
                return True
            return False
        except Exception as e:
            logging.error(f"处理自定义表情时出错: {str(e)}")
            return False

    async def edit_message_with_media(self, channel_id, message_id, text, media_path, media_type, media_info):
        """编辑消息以包含媒体文件"""
        try:
            # 注意：Telegram API 不支持直接编辑消息添加媒体
            # 我们需要删除原消息并发送新消息

            # 先删除原消息
            await self.bot.delete_message(
                chat_id=channel_id,
                message_id=message_id
            )

            # 根据媒体类型发送新消息
            with open(media_path, 'rb') as media_file:
                file_data = media_file.read()
                send_kwargs = {
                    'chat_id': channel_id,
                    'caption': text,
                    'parse_mode': 'Markdown',
                    'read_timeout': 1800,
                    'write_timeout': 1800
                }

                if media_type == 'photo':
                    send_kwargs['photo'] = file_data
                    await self.bot.send_photo(**send_kwargs)
                elif media_type == 'video':
                    send_kwargs['video'] = file_data
                    send_kwargs['supports_streaming'] = True

                    # 添加视频参数
                    if 'width' in media_info:
                        send_kwargs['width'] = media_info['width']
                    if 'height' in media_info:
                        send_kwargs['height'] = media_info['height']
                    if 'duration' in media_info:
                        send_kwargs['duration'] = media_info['duration']
                    if 'thumb_path' in media_info and os.path.exists(media_info['thumb_path']):
                        with open(media_info['thumb_path'], 'rb') as thumb_file:
                            send_kwargs['thumb'] = thumb_file.read()

                    await self.bot.send_video(**send_kwargs)

                    # 清理缩略图
                    if 'thumb_path' in media_info and os.path.exists(media_info['thumb_path']):
                        os.remove(media_info['thumb_path'])

                elif media_type == 'document':
                    send_kwargs['document'] = file_data
                    if 'filename' in media_info:
                        send_kwargs['filename'] = media_info['filename']
                    await self.bot.send_document(**send_kwargs)

            # 清理媒体文件
            await self.cleanup_file(media_path)
            logging.info(f"成功编辑消息并添加{media_type}")

        except Exception as e:
            logging.error(f"编辑消息添加媒体失败: {str(e)}")
            # 如果失败，尝试恢复原消息
            try:
                await self.bot.send_message(
                    chat_id=channel_id,
                    text=text + "\n\n⚠️ *媒体文件加载失败*",
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
            except Exception as e2:
                logging.error(f"恢复消息失败: {str(e2)}")

            # 清理媒体文件
            await self.cleanup_file(media_path)
            raise