# main.py - 主程序
import asyncio
import logging
from telegram.ext import Application, CommandHandler
from telethon import TelegramClient, events
from database import Database
from channel_manager import ChannelManager
from config import Config
from message_handler import MyMessageHandler
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    CallbackQuery
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters
)


class ForwardBot:
    def __init__(self, config):
        self.config = config
        self.db = Database(config.DATABASE_NAME)
        
        # Initialize Telegram bot
        self.application = Application.builder().token(config.TELEGRAM_TOKEN).build()
        
        # Initialize Telethon client
        self.client = TelegramClient(
            config.SESSION_NAME,
            config.API_ID,
            config.API_HASH
        )
        
        # Initialize components
        self.channel_manager = ChannelManager(self.db, config, self.client)
        self.message_handler = MyMessageHandler(self.db, self.client, self.application.bot)
        
        # Setup handlers
        self.setup_handlers()

    # In main.py
    def setup_handlers(self):
        """设置消息处理器"""
        # 命令处理器
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("channels", self.channels_command))
        
        # 添加频道管理处理器
        for handler in self.channel_manager.get_handlers():
            self.application.add_handler(handler)
        
        # 添加错误处理器
        self.application.add_error_handler(self.error_handler)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理错误"""
        logging.error(f"Update {update} caused error {context.error}")
        
    async def start_command(self, update, context):
        """处理 /start 命令"""
        if update.effective_user.id != self.config.OWNER_ID:
            await update.message.reply_text("未经授权的访问")
            return

        await update.message.reply_text(
            "👋 欢迎使用频道转发机器人!\n\n"
            "使用 /channels 管理频道和转发配对"
        )

    async def channels_command(self, update, context):
        """处理 /channels 命令"""
        if update.effective_user.id != self.config.OWNER_ID:
            await update.message.reply_text("未经授权的访问")
            return

        await self.channel_manager.show_channel_management(update.message, True)

        self.message_handler = MyMessageHandler(self.db, self.client, self.application.bot)

    async def start(self):
        """启动机器人"""
        try:
            # 启动 Telethon 客户端
            await self.client.start(phone=self.config.PHONE_NUMBER)
            
            # 启动清理任务
            await self.message_handler.start_cleanup_task()
            
            # 注册消息处理器
            @self.client.on(events.NewMessage)
            async def handle_new_message(event):
                await self.message_handler.handle_channel_message(event)
            
            # 启动机器人
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            print("Bot started successfully!")
            
            # 保持运行
            await self.client.run_until_disconnected()
            
        except Exception as e:
            logging.error(f"Error starting bot: {e}")
            raise
        finally:
            # 清理资源
            await self.stop()

    async def stop(self):
        """停止机器人"""
        try:
            if self.message_handler.cleanup_task:
                self.message_handler.cleanup_task.cancel()
            
            # 清理所有剩余的临时文件
            for file_path in list(self.message_handler.temp_files.keys()):
                await self.message_handler.cleanup_file(file_path)
                
            await self.application.stop()
            await self.client.disconnect()
            self.db.cleanup()
            print("Bot stopped successfully!")
        except Exception as e:
            logging.error(f"Error stopping bot: {e}")

async def main():
    """主函数"""
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('bot.log')
        ]
    )

    try:
        # 初始化配置
        config = Config()
        
        # 创建并启动机器人
        bot = ForwardBot(config)
        await bot.start()
        
    except Exception as e:
        logging.error(f"Critical error: {e}")
        import traceback
        logging.error(f"Traceback:\n{traceback.format_exc()}")
        raise

if __name__ == "__main__":
    asyncio.run(main())