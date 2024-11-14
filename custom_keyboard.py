from telegram import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove,
    KeyboardButtonRequestUsers,
    KeyboardButtonRequestChat
)
from locales import get_text

class CustomKeyboard:
    @staticmethod
    def get_share_keyboard(lang: str) -> ReplyKeyboardMarkup:
        """获取分享键盘"""
        keyboard = [
            [
                # Channel 和 Group 按钮 - 允许所有类型
                KeyboardButton(
                    text=get_text(lang, 'GROUP'),
                    request_chat=KeyboardButtonRequestChat(
                        request_id=3,
                        chat_is_channel=False
                    )
                ),
                KeyboardButton(
                    text=get_text(lang, 'CHANNEL'),
                    request_chat=KeyboardButtonRequestChat(
                        request_id=4,
                        chat_is_channel=True
                    )
                )
            ],
            [
                # User 和 Bot 按钮 - 允许所有类型
                KeyboardButton(
                    text=get_text(lang, 'USER'),
                    request_users=KeyboardButtonRequestUsers(
                        request_id=1,
                        user_is_bot=False,
                        max_quantity=1
                    )
                ),
                KeyboardButton(
                    text=get_text(lang, 'BOT'),
                    request_users=KeyboardButtonRequestUsers(
                        request_id=2,
                        user_is_bot=True,
                        max_quantity=1
                    )
                )
            ],
            [KeyboardButton(text=get_text(lang, 'cancel'))]
        ]
        
        return ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=True
        )

    @staticmethod
    def remove_keyboard():
        """移除自定义键盘"""
        return ReplyKeyboardRemove()