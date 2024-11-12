# channel_manager.py - 频道管理
# channel_management.py
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
import logging
from typing import Optional
from telethon import TelegramClient

# 定义会话状态
CHOOSING_CHANNEL_TYPE = 0
CHOOSING_ADD_METHOD = 1
WAITING_FOR_FORWARD = 2
WAITING_FOR_MANUAL_INPUT = 3

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
import logging
from typing import Optional
from telethon import TelegramClient

# 定义会话状态
CHOOSING_CHANNEL_TYPE = 0
CHOOSING_ADD_METHOD = 1
WAITING_FOR_FORWARD = 2
WAITING_FOR_MANUAL_INPUT = 3

class ChannelManager:
    def __init__(self, db, config, client: TelegramClient):
        self.db = db
        self.config = config
        self.client = client

    def get_handlers(self):
        """获取所有处理器"""
        handlers = [
            # 添加频道的 ConversationHandler
            ConversationHandler(
                entry_points=[
                    CallbackQueryHandler(self.start_add_channel, pattern='^add_channel$')
                ],
                states={
                    CHOOSING_CHANNEL_TYPE: [
                        CallbackQueryHandler(self.handle_channel_type_choice, pattern='^type_')
                    ],
                    CHOOSING_ADD_METHOD: [
                        CallbackQueryHandler(self.handle_add_method, pattern='^method_')
                    ],
                    WAITING_FOR_FORWARD: [
                        MessageHandler(filters.FORWARDED & ~filters.COMMAND, 
                                     self.handle_forwarded_message),
                        CallbackQueryHandler(self.cancel_add_channel, pattern='^cancel$')
                    ],
                    WAITING_FOR_MANUAL_INPUT: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, 
                                     self.handle_manual_input),
                        CallbackQueryHandler(self.cancel_add_channel, pattern='^cancel$')
                    ]
                },
                fallbacks=[
                    CommandHandler('cancel', self.cancel_add_channel),
                    CallbackQueryHandler(self.cancel_add_channel, pattern='^cancel$')
                ],
                name="add_channel",
                persistent=False
            ),
            
            # # 常规功能处理器
            # CallbackQueryHandler(self.show_remove_channel_options, pattern='^remove_channel$'),
            # CallbackQueryHandler(self.show_channel_list, pattern='^list_channels$'),
            # CallbackQueryHandler(self.view_channel_pairs, pattern='^view_pairs$'),
            # CallbackQueryHandler(self.handle_manage_pairs, pattern='^manage_pairs$'),
            # CallbackQueryHandler(self.handle_channel_selection, pattern='^select_'),
            # CallbackQueryHandler(self.handle_pair_confirmation, pattern='^confirm_pair_'),
            # CallbackQueryHandler(self.handle_remove_confirmation, pattern='^confirm_remove_'),
            # CallbackQueryHandler(self.handle_remove_channel, pattern='^remove_'),
            # CallbackQueryHandler(self.handle_pair_channel, pattern='^pair_'),
            # CallbackQueryHandler(self.show_channel_management, pattern='^channel_management$'),
            # # 更新配对管理相关的处理器

            # 删除频道相关
            CallbackQueryHandler(
                self.show_remove_channel_options, 
                pattern='^remove_channel$'
            ),
            CallbackQueryHandler(
                self.handle_remove_channel, 
                pattern='^remove_channel_[0-9]+$'
            ),
            CallbackQueryHandler(
                self.handle_remove_confirmation, 
                pattern='^confirm_remove_channel_[0-9]+$'
            ),

            # 频道列表
            CallbackQueryHandler(
                self.show_channel_list, 
                pattern='^list_channels$'
            ),

            # 配对管理相关
            CallbackQueryHandler(
                self.view_channel_pairs, 
                pattern='^view_pairs$'
            ),
            CallbackQueryHandler(
                self.handle_manage_specific_pair, 
                pattern='^manage_pair_[0-9]+(_[0-9]+)?$'
            ),
            CallbackQueryHandler(
                self.handle_add_specific_pair, 
                pattern='^add_pair_[0-9]+_[0-9]+(_add)?$'
            ),
            CallbackQueryHandler(
                self.handle_remove_specific_pair, 
                pattern='^remove_pair_[0-9]+_[0-9]+$'
            ),
            CallbackQueryHandler(
                self.handle_confirm_remove_pair, 
                pattern='^confirm_remove_pair_[0-9]+_[0-9]+$'
            ),

        ]
        return handlers


    async def start_add_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """开始添加频道流程"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [
                InlineKeyboardButton("监控频道", callback_data="type_monitor"),
                InlineKeyboardButton("转发频道", callback_data="type_forward")
            ],
            [InlineKeyboardButton("取消", callback_data="cancel")]
        ]
        
        await query.message.edit_text(
            "选择要添加的频道类型:\n\n"
            "• 监控频道: 用于监控消息\n"
            "• 转发频道: 用于转发消息",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CHOOSING_CHANNEL_TYPE

    async def handle_channel_type_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理频道类型选择"""
        query = update.callback_query
        await query.answer()

        channel_type = query.data.split('_')[1].upper()
        context.user_data['channel_type'] = channel_type

        keyboard = [
            [
                InlineKeyboardButton("转发消息", callback_data="method_forward"),
                InlineKeyboardButton("输入ID", callback_data="method_manual")
            ],
            [InlineKeyboardButton("取消", callback_data="cancel")]
        ]

        await query.message.edit_text(
            f"请选择添加{channel_type}频道的方式:\n\n"
            "• 转发消息: 从目标频道转发任意消息\n"
            "• 输入ID: 直接输入频道ID",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return CHOOSING_ADD_METHOD

    async def handle_add_method(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理添加方法选择"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "method_forward":
            await query.message.edit_text(
                "请从目标频道转发一条消息。\n\n"
                "提示: 你可以点击消息，然后选择'Forward'来转发。\n\n"
                "输入 /cancel 取消操作。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("取消", callback_data="cancel")
                ]])
            )
            return WAITING_FOR_FORWARD
            
        elif query.data == "method_manual":
            await query.message.edit_text(
                "请输入频道ID。\n\n"
                "提示: 频道ID是-100开头的数字，可以通过复制频道消息链接获取。\n"
                "例如: -1001234567890\n\n"
                "输入 /cancel 取消操作。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("取消", callback_data="cancel")
                ]])
            )
            return WAITING_FOR_MANUAL_INPUT

    async def handle_forwarded_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理转发的消息"""
        try:
            message = update.message
            
            if not message.forward_from_chat:
                await message.reply_text(
                    "❌ 请转发一条来自目标频道的消息。",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("取消", callback_data="cancel")
                    ]])
                )
                return WAITING_FOR_FORWARD

            chat = message.forward_from_chat
            channel_type = context.user_data.get('channel_type')
            
            success = self.db.add_channel(
                channel_id=chat.id,
                channel_name=chat.title,
                channel_username=chat.username,
                channel_type=channel_type
            )

            if success:
                await message.reply_text(
                    f"✅ 频道添加成功!\n\n"
                    f"名称: {chat.title}\n"
                    f"ID: {chat.id}\n"
                    f"类型: {'监控频道' if channel_type == 'MONITOR' else '转发频道'}"
                )
            else:
                await message.reply_text("❌ 添加频道失败")

            context.user_data.clear()
            return ConversationHandler.END
            
        except Exception as e:
            logging.error(f"Error in handle_forwarded_message: {e}")
            await message.reply_text("❌ 处理消息时发生错误")
            return ConversationHandler.END

    async def handle_manual_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理手动输入的频道ID"""
        try:
            message = update.message
            input_text = message.text.strip()
            
            try:
                # 处理输入的ID
                if input_text.startswith('-'):
                    channel_id = int(input_text)
                else:
                    if input_text.startswith('100'):
                        channel_id = -int(input_text)
                    else:
                        channel_id = -int(f"100{input_text}")

                # 使用 Telethon client 获取频道信息
                chat = await self.client.get_entity(channel_id)
                success = self.db.add_channel(
                    channel_id=chat.id,
                    channel_name=getattr(chat, 'title', None) or getattr(chat, 'first_name', 'Unknown'),
                    channel_username=getattr(chat, 'username', None),
                    channel_type=context.user_data.get('channel_type')
                )

                if success:
                    await message.reply_text(
                        f"✅ 频道添加成功!\n\n"
                        f"名称: {getattr(chat, 'title', None) or getattr(chat, 'first_name', 'Unknown')}\n"
                        f"ID: {chat.id}\n"
                        f"用户名: @{getattr(chat, 'username', 'N/A')}"
                    )
                else:
                    await message.reply_text("❌ 添加频道失败")

                context.user_data.clear()
                return ConversationHandler.END

            except ValueError:
                await message.reply_text(
                    "❌ 无效的频道ID格式。\n\n"
                    "请重新输入或使用 /cancel 取消"
                )
                return WAITING_FOR_MANUAL_INPUT
                
            except Exception as e:
                logging.error(f"Error getting channel info: {e}")
                await message.reply_text(
                    "❌ 无法获取频道信息。请确保:\n"
                    "1. ID格式正确\n"
                    "2. Bot已加入该频道\n"
                    "3. 您有权限访问该频道\n\n"
                    "请重新输入或使用 /cancel 取消"
                )
                return WAITING_FOR_MANUAL_INPUT

        except Exception as e:
            logging.error(f"Error in handle_manual_input: {e}")
            await message.reply_text(
                "❌ 处理输入时发生错误。\n"
                "请重新输入或使用 /cancel 取消"
            )
            return WAITING_FOR_MANUAL_INPUT

    async def cancel_add_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """取消添加频道"""
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            await query.message.edit_text("❌ 已取消添加频道")
        else:
            await update.message.reply_text("❌ 已取消添加频道")
        
        context.user_data.clear()
        return ConversationHandler.END



    async def handle_remove_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理删除确认"""
        query = update.callback_query
        await query.answer()

        try:
            channel_id = int(query.data.split('_')[3])
            success = self.db.remove_channel(channel_id)

            if success:
                await query.message.edit_text(
                    "✅ 频道已删除",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("返回", callback_data="channel_management")
                    ]])
                )
            else:
                await query.message.edit_text(
                    "❌ 删除失败",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("重试", callback_data="remove_channel")
                    ]])
                )
        except Exception as e:
            logging.error(f"Error in handle_remove_confirmation: {e}")
            await query.message.edit_text(
                "❌ 删除频道时发生错误",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="channel_management")
                ]])
            )



    async def handle_remove_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理删除频道请求"""
        query = update.callback_query
        await query.answer()
        
        try:
            # 确保是删除频道而不是删除配对
            data = query.data.split('_')
            if len(data) < 2 or data[0] != 'remove' or data[1] == 'pair':
                logging.error(f"Invalid remove channel callback data: {query.data}")
                await query.message.edit_text(
                    "❌ 无效的操作",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("返回", callback_data="channel_management")
                    ]])
                )
                return

            channel_id = int(data[1])
            channel_info = self.db.get_channel_info(channel_id)
            
            if not channel_info:
                await query.message.edit_text(
                    "❌ 未找到频道信息",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("返回", callback_data="channel_management")
                    ]])
                )
                return

            keyboard = [
                [
                    InlineKeyboardButton("✅ 确认删除", callback_data=f"confirm_remove_channel_{channel_id}"),
                    InlineKeyboardButton("❌ 取消", callback_data="remove_channel")
                ]
            ]

            await query.message.edit_text(
                f"确定要删除此频道吗?\n\n"
                f"频道名称: {channel_info['channel_name']}\n"
                f"频道ID: {channel_info['channel_id']}\n"
                f"类型: {'监控频道' if channel_info['channel_type'] == 'MONITOR' else '转发频道'}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logging.error(f"Error in handle_remove_channel: {e}")
            await query.message.edit_text(
                "❌ 处理删除请求时发生错误",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="channel_management")
                ]])
            )

    async def show_remove_channel_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """显示可删除的频道列表"""
        query = update.callback_query
        await query.answer()
        
        monitor_channels = self.db.get_channels_by_type('MONITOR')
        forward_channels = self.db.get_channels_by_type('FORWARD')

        if not monitor_channels and not forward_channels:
            await query.message.edit_text(
                "当前没有任何频道。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="channel_management")
                ]])
            )
            return

        keyboard = []
        if monitor_channels:
            keyboard.append([InlineKeyboardButton("-- 监控频道 --", callback_data="dummy")])
            for channel in monitor_channels:
                keyboard.append([InlineKeyboardButton(
                    f"🔍 {channel['channel_name']}",
                    callback_data=f"remove_channel_{channel['channel_id']}"
                )])

        if forward_channels:
            keyboard.append([InlineKeyboardButton("-- 转发频道 --", callback_data="dummy")])
            for channel in forward_channels:
                keyboard.append([InlineKeyboardButton(
                    f"📢 {channel['channel_name']}",
                    callback_data=f"remove_channel_{channel['channel_id']}"
                )])

        keyboard.append([InlineKeyboardButton("返回", callback_data="channel_management")])

        await query.message.edit_text(
            "选择要删除的频道:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )



    async def show_channel_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """显示频道列表"""
        query = update.callback_query
        await query.answer()
        
        monitor_channels = self.db.get_channels_by_type('MONITOR')
        forward_channels = self.db.get_channels_by_type('FORWARD')

        text = "📋 频道列表\n\n"

        if monitor_channels:
            text += "🔍 监控频道:\n"
            for idx, channel in enumerate(monitor_channels, 1):
                text += f"{idx}. {channel['channel_name']}\n"
                text += f"   ID: {channel['channel_id']}\n"
                text += f"   用户名: @{channel['channel_username'] or 'N/A'}\n\n"

        if forward_channels:
            text += "\n📢 转发频道:\n"
            for idx, channel in enumerate(forward_channels, 1):
                text += f"{idx}. {channel['channel_name']}\n"
                text += f"   ID: {channel['channel_id']}\n"
                text += f"   用户名: @{channel['channel_username'] or 'N/A'}\n\n"

        if not monitor_channels and not forward_channels:
            text += "暂无频道配置"

        keyboard = [[InlineKeyboardButton("返回", callback_data="channel_management")]]
        
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # 修改 ChannelManager 类中的方法

    async def handle_add_specific_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理添加特定配对"""
        query = update.callback_query
        await query.answer()
        
        try:
            # 解析数据
            parts = query.data.split('_')
            if len(parts) >= 4:
                monitor_id = int(parts[2])
                forward_id = int(parts[3])
            else:
                raise ValueError("Invalid callback data format")
            
            success = self.db.add_channel_pair(monitor_id, forward_id)
            
            if success:
                await query.message.edit_text(
                    "✅ 配对添加成功!",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("返回配对管理", callback_data=f"manage_pair_{monitor_id}_1")
                    ]])
                )
            else:
                await query.message.edit_text(
                    "❌ 配对添加失败",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("重试", callback_data=f"manage_pair_{monitor_id}_1")
                    ]])
                )
        except (ValueError, IndexError) as e:
            logging.error(f"Error parsing callback data: {e}")
            await query.message.edit_text(
                "❌ 操作无效",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="view_pairs")
                ]])
            )
        except Exception as e:
            logging.error(f"Error in handle_add_specific_pair: {e}")
            await query.message.edit_text(
                "❌ 操作失败",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="view_pairs")
                ]])
            )


    async def handle_remove_specific_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理移除配对"""
        query = update.callback_query
        await query.answer()
        
        try:
            # 解析callback_data: "remove_pair_{monitor_id}_{forward_id}"
            parts = query.data.split('_')
            if len(parts) < 4:
                raise ValueError("Invalid callback data format")
            
            monitor_id = int(parts[2])
            forward_id = int(parts[3])
            
            # 获取频道信息用于显示
            monitor_info = self.db.get_channel_info(monitor_id)
            forward_info = self.db.get_channel_info(forward_id)
            
            if not monitor_info or not forward_info:
                await query.message.edit_text(
                    "❌ 未找到频道信息",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("返回", callback_data=f"manage_pair_{monitor_id}_1")
                    ]])
                )
                return
            
            # 显示确认消息
            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ 确认移除", 
                        callback_data=f"confirm_remove_pair_{monitor_id}_{forward_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ 取消", 
                        callback_data=f"manage_pair_{monitor_id}_1"
                    )
                ]
            ]
            
            await query.message.edit_text(
                f"确定要移除以下配对？\n\n"
                f"监控频道: {monitor_info['channel_name']}\n"
                f"转发频道: {forward_info['channel_name']}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logging.error(f"Error in handle_remove_specific_pair: {e}")
            await query.message.edit_text(
                "❌ 操作失败",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="view_pairs")
                ]])
            )

    async def handle_confirm_remove_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理确认移除配对"""
        query = update.callback_query
        await query.answer()
        
        try:
            # 解析callback_data: "confirm_remove_pair_{monitor_id}_{forward_id}"
            parts = query.data.split('_')
            if len(parts) < 5:
                raise ValueError("Invalid callback data format")
            
            monitor_id = int(parts[3])
            forward_id = int(parts[4])
            
            success = self.db.remove_channel_pair(monitor_id, forward_id)
            
            if success:
                await query.message.edit_text(
                    "✅ 配对已移除",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("返回配对管理", callback_data=f"manage_pair_{monitor_id}_1")
                    ]])
                )
            else:
                await query.message.edit_text(
                    "❌ 移除配对失败",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("重试", callback_data=f"manage_pair_{monitor_id}_1")
                    ]])
                )
            
        except Exception as e:
            logging.error(f"Error in handle_confirm_remove_pair: {e}")
            await query.message.edit_text(
                "❌ 操作失败",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="view_pairs")
                ]])
            )

    async def handle_manage_pairs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理配对管理"""
        query = update.callback_query
        await query.answer()

        monitor_channels = self.db.get_channels_by_type('MONITOR')
        if not monitor_channels:
            await query.message.edit_text(
                "没有可用的监控频道来创建配对。请先添加监控频道。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="channel_management")
                ]])
            )
            return

        keyboard = []
        for channel in monitor_channels:
            keyboard.append([InlineKeyboardButton(
                f"🔍 {channel['channel_name']}",
                callback_data=f"select_{channel['channel_id']}"
            )])
        keyboard.append([InlineKeyboardButton("返回", callback_data="channel_management")])

        await query.message.edit_text(
            "选择要配对的监控频道:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def handle_channel_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理频道选择"""
        query = update.callback_query
        await query.answer()

        monitor_id = int(query.data.split('_')[1])
        forward_channels = self.db.get_channels_by_type('FORWARD')

        if not forward_channels:
            await query.message.edit_text(
                "没有可用的转发频道。请先添加转发频道。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="manage_pairs")
                ]])
            )
            return

        keyboard = []
        for channel in forward_channels:
            keyboard.append([InlineKeyboardButton(
                f"📢 {channel['channel_name']}",
                callback_data=f"pair_{monitor_id}_{channel['channel_id']}"
            )])
        keyboard.append([InlineKeyboardButton("返回", callback_data="manage_pairs")])

        await query.message.edit_text(
            "选择要配对的转发频道:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def handle_pair_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理频道配对请求"""
        query = update.callback_query
        await query.answer()
        
        try:
            _, monitor_id, forward_id = query.data.split('_')
            monitor_info = self.db.get_channel_info(int(monitor_id))
            forward_info = self.db.get_channel_info(int(forward_id))
            
            if not monitor_info or not forward_info:
                await query.message.edit_text(
                    "❌ 无法获取频道信息",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("返回", callback_data="manage_pairs")
                    ]])
                )
                return

            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ 确认配对", 
                        callback_data=f"confirm_pair_{monitor_id}_{forward_id}"
                    ),
                    InlineKeyboardButton("❌ 取消", callback_data="manage_pairs")
                ]
            ]

            await query.message.edit_text(
                f"确认创建以下配对？\n\n"
                f"监控频道: {monitor_info['channel_name']}\n"
                f"转发频道: {forward_info['channel_name']}\n\n"
                f"配对后，来自监控频道的消息将自动转发到转发频道。",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except Exception as e:
            logging.error(f"Error in handle_pair_channel: {e}")
            await query.message.edit_text(
                "❌ 处理配对请求时发生错误",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="manage_pairs")
                ]])
            )

    async def handle_pair_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理配对确认"""
        query = update.callback_query
        await query.answer()
        
        try:
            _, monitor_id, forward_id = query.data.split('_')[2:]
            success = self.db.add_channel_pair(int(monitor_id), int(forward_id))

            if success:
                await query.message.edit_text(
                    "✅ 频道配对成功!",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("返回", callback_data="view_pairs")
                    ]])
                )
            else:
                await query.message.edit_text(
                    "❌ 配对失败",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("重试", callback_data="manage_pairs")
                    ]])
                )
        except Exception as e:
            logging.error(f"Error in handle_pair_confirmation: {e}")
            await query.message.edit_text(
                "❌ 处理配对确认时发生错误",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="manage_pairs")
                ]])
            )

    async def view_channel_pairs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """显示频道配对"""
        query = update.callback_query
        await query.answer()
        
        try:
            monitor_channels = self.db.get_channels_by_type('MONITOR')
            
            if not monitor_channels:
                await query.message.edit_text(
                    "暂无监控频道，请先添加监控频道。",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("添加频道", callback_data="add_channel"),
                        InlineKeyboardButton("返回", callback_data="channel_management")
                    ]])
                )
                return

            text = "📱 频道配对管理\n\n选择要管理配对的监控频道:\n"
            keyboard = []
            
            for channel in monitor_channels:
                # 获取前5个转发频道作为预览
                forward_result = self.db.get_forward_channels(channel['channel_id'], page=1, per_page=5)
                text += f"\n🔍 {channel['channel_name']}\n"
                
                if forward_result['channels']:
                    text += "当前配对:\n"
                    for fwd in forward_result['channels']:
                        text += f"└─ 📢 {fwd['channel_name']}\n"
                    if forward_result['total'] > 5:
                        text += f"... 等共 {forward_result['total']} 个频道\n"
                else:
                    text += "└─ (暂无配对)\n"
                
                keyboard.append([InlineKeyboardButton(
                    f"管理 {channel['channel_name']} 的配对",
                    callback_data=f"manage_pair_{channel['channel_id']}_1"
                )])

            keyboard.append([InlineKeyboardButton("返回", callback_data="channel_management")])
            
            # 检查消息长度，如果太长则分页显示
            if len(text) > 4096:
                text = text[:4000] + "\n\n... (更多频道请使用管理按钮查看)"
            
            await query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logging.error(f"Error in view_channel_pairs: {e}")
            await query.message.edit_text(
                "获取频道配对信息时出现错误，请稍后重试。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="channel_management")
                ]])
            )

    async def show_channel_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """显示频道管理菜单"""
        if isinstance(update, Update) and update.callback_query:
            query = update.callback_query
            await query.answer()
            is_new_message = False
            message = query.message
        else:
            is_new_message = True
            message = update

        keyboard = [
            [
                InlineKeyboardButton("添加频道", callback_data="add_channel"),
                InlineKeyboardButton("删除频道", callback_data="remove_channel")
            ],
            [
                InlineKeyboardButton("频道列表", callback_data="list_channels"),
                InlineKeyboardButton("配对管理", callback_data="view_pairs")
            ]
        ]

        menu_text = (
            "📺 频道管理\n\n"
            "• 添加监控或转发频道\n"
            "• 删除现有频道\n"
            "• 查看频道列表\n"
            "• 管理频道配对"
        )

        try:
            if is_new_message:
                await message.reply_text(menu_text, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await message.edit_text(menu_text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            logging.error(f"Error in show_channel_management: {e}")

    async def handle_manage_specific_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理特定频道的配对管理"""
        query = update.callback_query
        await query.answer()
        
        try:
            parts = query.data.split('_')
            monitor_id = int(parts[2])
            page = int(parts[3]) if len(parts) > 3 else 1
            
            monitor_info = self.db.get_channel_info(monitor_id)
            if not monitor_info:
                await query.message.edit_text(
                    "未找到频道信息",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("返回管理", callback_data="channel_management")
                    ]])
                )
                return
            
            text = f"🔍 {monitor_info['channel_name']} 的配对管理\n\n"
            keyboard = []
            
            # 获取当前配对
            current_pairs = self.db.get_forward_channels(monitor_id, page)
            if current_pairs['channels']:
                text += "当前配对:\n"
                for channel in current_pairs['channels']:
                    text += f"📢 {channel['channel_name']}\n"
                    keyboard.append([InlineKeyboardButton(
                        f"❌ 移除 {channel['channel_name']}",
                        callback_data=f"remove_pair_{monitor_id}_{channel['channel_id']}"
                    )])
            else:
                text += "当前无配对\n"

            # 获取可用的转发频道
            available_channels = self.db.get_unpaired_forward_channels(monitor_id, page)
            if available_channels['channels']:
                text += "\n可添加的转发频道:\n"
                for channel in available_channels['channels']:
                    keyboard.append([InlineKeyboardButton(
                        f"➕ 添加 {channel['channel_name']}",
                        callback_data=f"add_pair_{monitor_id}_{channel['channel_id']}_add"
                    )])

            # 添加导航按钮
            navigation = []
            if page > 1:
                navigation.append(InlineKeyboardButton(
                    "⬅️ 上一页", 
                    callback_data=f"manage_pair_{monitor_id}_{page-1}"
                ))
            if (current_pairs['total_pages'] > page or 
                available_channels['total_pages'] > page):
                navigation.append(InlineKeyboardButton(
                    "➡️ 下一页", 
                    callback_data=f"manage_pair_{monitor_id}_{page+1}"
                ))
            if navigation:
                keyboard.append(navigation)

            # 添加返回按钮
            keyboard.append([
                InlineKeyboardButton("返回配对列表", callback_data="view_pairs"),
                InlineKeyboardButton("返回主菜单", callback_data="channel_management")
            ])

            await query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logging.error(f"Error in handle_manage_specific_pair: {e}")
            await query.message.edit_text(
                "处理配对管理时出现错误，请稍后重试。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("返回", callback_data="channel_management")
                ]])
            )
