# message_handler.py
from telethon import TelegramClient, events
import os
import logging
import traceback
from typing import Optional, BinaryIO
from tempfile import NamedTemporaryFile
import asyncio
from datetime import datetime, timedelta
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

            except Exception as e:
                logging.error(get_text('en', 'cleanup_task_error', error=str(e)))
            
            # 每小时运行一次
            await asyncio.sleep(3600)

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

            for channel in forward_channels:
                try:
                    await self.handle_forward_message(message, chat, channel)
                except Exception as e:
                    logging.error(get_text('en', 'forward_channel_error', 
                                         channel_id=channel.get('channel_id'), 
                                         error=str(e)))
                    continue

        except Exception as e:
            logging.error(get_text('en', 'message_handler_error', error=str(e)))
            logging.error(get_text('en', 'error_details', details=traceback.format_exc()))

    async def handle_media_send(self, message, channel_id, from_chat, media_type: str, reply_to_message_id: int = None):
        """处理媒体发送并确保清理"""
        tmp = None
        file_path = None
        chunk_size = 20 * 1024 * 1024  # 20MB 分块
        
        try:
            # 获取文件大小
            file_size = getattr(message.media, 'file_size', 0) or getattr(message.media, 'size', 0)
            logging.info(f"开始处理文件，大小: {file_size / (1024*1024):.2f}MB")

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
            logging.info("文件下载完成，准备发送")
        
            if not os.path.exists(file_path):
                raise Exception(get_text('en', 'downloaded_file_not_found', file_path=file_path))

            # 记录临时文件
            self.temp_files[file_path] = datetime.now()
        
            # 只有在没有回复消息时才添加说明文字
            caption = None if reply_to_message_id else f"Forwarded from {getattr(from_chat, 'title', 'Unknown Channel')}"
            if not reply_to_message_id and getattr(from_chat, 'username', None):
                caption += f" (@{from_chat.username})"
        
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
                        # 获取原始视频的参数
                        video = message.media.video
                        send_kwargs.update({
                            'video': file_data,
                            'width': video.width,
                            'height': video.height,
                            'duration': video.duration,
                            'supports_streaming': True
                        })
                        # 如果有缩略图
                        if hasattr(video, 'thumb') and video.thumb:
                            send_kwargs['thumb'] = await self.client.download_media(video.thumb)
                        await self.bot.send_video(**send_kwargs)
                    elif media_type == 'document':
                        # 获取文件名
                        if hasattr(message.media.document, 'attributes'):
                            for attr in message.media.document.attributes:
                                if hasattr(attr, 'file_name'):
                                    send_kwargs['filename'] = attr.file_name
                                    break
                        send_kwargs['document'] = file_data
                        await self.bot.send_document(**send_kwargs)

                    logging.info(f"文件发送成功: {media_type}" + 
                           (f" (回复到消息: {reply_to_message_id})" if reply_to_message_id else ""))
                finally:
                    del file_data  # 释放内存
                    # 清理缩略图
                    if 'thumb' in send_kwargs and os.path.exists(send_kwargs['thumb']):
                        os.remove(send_kwargs['thumb'])

            # 发送成功后立即删除文件
            await self.cleanup_file(file_path)
        
        except Exception as e:
            logging.error(f"处理媒体文件时出错: {str(e)}")
            if file_path:
                await self.cleanup_file(file_path)
            raise
        finally:
            # 确保临时文件被关闭和删除
            if tmp and not tmp.closed:
                tmp.close()
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    logging.error(f"删除临时文件失败: {str(e)}")

    async def handle_forward_message(self, message, from_chat, to_channel):
        """处理消息转发"""
        if not message or not from_chat or not to_channel:
            logging.error(get_text('en', 'missing_parameters'))
            return

        try:
            channel_id = to_channel.get('channel_id')
            channel_id = int("-100"+str(channel_id))
            if not channel_id:
                logging.error(get_text('en', 'invalid_channel_id'))
                return

            forwarded_msg = None

            # 尝试直接转发
            try:
                forwarded_msg = await self.bot.forward_message(
                    chat_id=channel_id,
                    from_chat_id=from_chat.id,
                    message_id=message.id
                )
                logging.info(get_text('en', 'forward_success', channel_id=channel_id))
                return
            except Exception as e:
                logging.warning(get_text('en', 'direct_forward_failed', error=str(e)))

            # 如果直接转发失败，处理文本消息
            if getattr(message, 'text', None) or getattr(message, 'caption', None):
                content = message.text or message.caption
                # 简化的转发格式
                forwarded_text = f"Forwarded from {getattr(from_chat, 'title', 'Unknown Channel')}"
                if getattr(from_chat, 'username', None):
                    forwarded_text += f" (@{from_chat.username})"
                forwarded_text += f"\n\n{content}"
            
                # 发送文本消息
                forwarded_msg = await self.bot.send_message(
                    chat_id=channel_id,
                    text=forwarded_text,
                    disable_web_page_preview=True
                )
                logging.info(get_text('en', 'text_send_success', channel_id=channel_id))

            # 处理媒体消息
            if getattr(message, 'media', None):
                media_types = []
                if hasattr(message.media, 'photo'):
                    media_types.append('photo')
                elif hasattr(message.media, 'video'):
                    media_types.append('video')
                elif hasattr(message.media, 'document'):
                    media_types.append('document')

                for media_type in media_types:
                    try:
                        await self.handle_media_send(
                            message=message,
                            channel_id=channel_id,
                            from_chat=from_chat,
                            media_type=media_type,
                            reply_to_message_id=forwarded_msg.message_id if forwarded_msg else None
                        )
                    except Exception as e:
                        logging.error(f"处理{media_type}时出错: {str(e)}")

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