# message_handler.py - 消息处理
# 修改后的消息处理器

from telethon import TelegramClient, events
import os
import logging
import traceback
from typing import Optional, BinaryIO
from tempfile import NamedTemporaryFile
import asyncio
from datetime import datetime, timedelta

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
                                logging.info(f"Cleaned up old temp file: {file_path}")
                            except Exception as e:
                                logging.error(f"Error cleaning up old file {file_path}: {e}")
                        files_to_remove.append(file_path)

                # 从跟踪列表中移除已清理的文件
                for file_path in files_to_remove:
                    self.temp_files.pop(file_path, None)

            except Exception as e:
                logging.error(f"Error in cleanup task: {e}")
            
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
                    logging.error(f"Error forwarding to channel {channel.get('channel_id')}: {e}")
                    continue

        except Exception as e:
            logging.error(f"Error in handle_channel_message: {str(e)}")
            logging.error(f"Full error details: {traceback.format_exc()}")

    async def handle_media_send(self, message, channel_id, from_chat, media_type: str):
        """处理媒体发送并确保清理"""
        tmp = None
        file_path = None
        
        try:
            tmp = NamedTemporaryFile(delete=False)
            file_path = await self.client.download_media(
                message.media, 
                file=tmp.name,
                progress_callback=self.download_progress_callback
            )
            
            if not file_path:
                raise Exception("Failed to download media")

            caption = f"转发自: {getattr(from_chat, 'title', 'Unknown Channel')}"
            
            # 记录临时文件
            self.temp_files[file_path] = datetime.now()
            
            # 确保文件存在
            if not os.path.exists(file_path):
                raise Exception(f"Downloaded file not found: {file_path}")

            # 发送媒体文件
            with open(file_path, 'rb') as media_file:
                if media_type == 'photo':
                    await self.bot.send_photo(
                        chat_id=channel_id,
                        photo=media_file,
                        caption=caption
                    )
                elif media_type == 'video':
                    await self.bot.send_video(
                        chat_id=channel_id,
                        video=media_file,
                        caption=caption
                    )
                elif media_type == 'document':
                    await self.bot.send_document(
                        chat_id=channel_id,
                        document=media_file,
                        caption=caption
                    )

            logging.info(f"Successfully sent {media_type} to channel {channel_id}")
            
            # 发送成功后立即删除文件
            await self.cleanup_file(file_path)
            
        except Exception as e:
            logging.error(f"Error sending {media_type}: {e}")
            if file_path:
                await self.cleanup_file(file_path)
            raise
        finally:
            # 确保临时文件被关闭
            if tmp and not tmp.closed:
                tmp.close()

    async def cleanup_file(self, file_path: str):
        """清理单个文件"""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                self.temp_files.pop(file_path, None)
                logging.info(f"Successfully cleaned up file: {file_path}")
        except Exception as e:
            logging.error(f"Error cleaning up file {file_path}: {e}")

    async def handle_forward_message(self, message, from_chat, to_channel):
        """处理消息转发"""
        if not message or not from_chat or not to_channel:
            logging.error("Missing required parameters for message forwarding")
            return

        try:
            channel_id = to_channel.get('channel_id')
            channel_id = int("-100"+str(channel_id))
            if not channel_id:
                logging.error("Invalid channel ID")
                return

            # 尝试直接转发
            try:
                await self.bot.forward_message(
                    chat_id=channel_id,
                    from_chat_id=from_chat.id,
                    message_id=message.id
                )
                logging.info(f"Successfully forwarded message to channel {channel_id}")
                return
            except Exception as e:
                logging.warning(f"Direct forward failed, trying alternative method: {e}")

            # 处理文本消息
            if getattr(message, 'text', None):
                channel_title = getattr(from_chat, 'title', 'Unknown Channel')
                channel_username = getattr(from_chat, 'username', None)
                
                forwarded_text = (
                    f"转发自: {channel_title}\n"
                    f"{'@' + channel_username if channel_username else '私有频道'}\n"
                    f"{'_'*30}\n\n"
                    f"{message.text}"
                )
                
                await self.bot.send_message(
                    chat_id=channel_id,
                    text=forwarded_text
                )
                logging.info(f"Successfully sent text message to channel {channel_id}")

            # 处理媒体消息
            if getattr(message, 'media', None):
                if hasattr(message, 'photo') and message.photo:
                    await self.handle_media_send(message, channel_id, from_chat, 'photo')
                elif hasattr(message, 'video') and message.video:
                    await self.handle_media_send(message, channel_id, from_chat, 'video')
                elif hasattr(message, 'document') and message.document:
                    await self.handle_media_send(message, channel_id, from_chat, 'document')

        except Exception as e:
            logging.error(f"Error in handle_forward_message: {e}")
            logging.error(f"Full error details: {traceback.format_exc()}")
            raise

    async def download_progress_callback(self, current, total):
        """下载进度回调"""
        if total:
            percentage = current * 100 / total
            if percentage % 20 == 0:  # 每20%记录一次
                logging.info(f"Download progress: {percentage:.1f}%")
