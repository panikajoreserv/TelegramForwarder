# database.py
import sqlite3
from typing import List, Dict, Optional, Any
import logging
from datetime import datetime

class Database:
    def __init__(self, db_name: str):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.setup_database()

    def setup_database(self):
        """初始化数据库表"""
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY,
                channel_name TEXT,
                channel_username TEXT,
                channel_type TEXT CHECK(channel_type IN ('MONITOR', 'FORWARD')),
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS channel_pairs (
                monitor_channel_id INTEGER,
                forward_channel_id INTEGER,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                PRIMARY KEY (monitor_channel_id, forward_channel_id),
                FOREIGN KEY (monitor_channel_id) REFERENCES channels(channel_id),
                FOREIGN KEY (forward_channel_id) REFERENCES channels(channel_id)
            );

            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                language TEXT DEFAULT 'en',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_channels_type 
            ON channels(channel_type);
            
            CREATE INDEX IF NOT EXISTS idx_channels_active 
            ON channels(is_active);
            
            CREATE INDEX IF NOT EXISTS idx_pairs_monitor 
            ON channel_pairs(monitor_channel_id);
            
            CREATE INDEX IF NOT EXISTS idx_pairs_forward 
            ON channel_pairs(forward_channel_id);
            
            CREATE INDEX IF NOT EXISTS idx_pairs_active 
            ON channel_pairs(is_active);
        ''')
        self.conn.commit()

    def get_user_language(self, user_id: int) -> str:
        """获取用户语言设置"""
        try:
            self.cursor.execute('''
                SELECT language FROM user_preferences 
                WHERE user_id = ?
            ''', (user_id,))
            result = self.cursor.fetchone()
            return result[0] if result else 'en'
        except sqlite3.Error as e:
            logging.error(f"Error getting user language: {e}")
            return 'en'

    def set_user_language(self, user_id: int, language: str) -> bool:
        """设置用户语言偏好"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO user_preferences (user_id, language, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, language))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error setting user language: {e}")
            return False

    def add_channel(self, channel_id: int, channel_name: str, 
                   channel_username: Optional[str], channel_type: str) -> bool:
        """添加新频道"""
        try:
            # 首先检查频道是否已存在
            self.cursor.execute('''
                SELECT channel_id, is_active FROM channels 
                WHERE channel_id = ?
            ''', (channel_id,))
            existing = self.cursor.fetchone()
            
            if existing:
                # 如果频道存在但被停用，重新激活它
                if not existing[1]:
                    self.cursor.execute('''
                        UPDATE channels 
                        SET is_active = 1,
                            channel_name = ?,
                            channel_username = ?,
                            channel_type = ?,
                            added_date = CURRENT_TIMESTAMP
                        WHERE channel_id = ?
                    ''', (channel_name, channel_username, channel_type, channel_id))
                else:
                    # 更新现有频道信息
                    self.cursor.execute('''
                        UPDATE channels 
                        SET channel_name = ?,
                            channel_username = ?,
                            channel_type = ?
                        WHERE channel_id = ?
                    ''', (channel_name, channel_username, channel_type, channel_id))
            else:
                # 添加新频道
                self.cursor.execute('''
                    INSERT INTO channels 
                    (channel_id, channel_name, channel_username, channel_type) 
                    VALUES (?, ?, ?, ?)
                ''', (channel_id, channel_name, channel_username, channel_type))
            
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error in add_channel: {e}")
            return False

    def remove_channel(self, channel_id: int) -> bool:
        """移除频道"""
        try:
            # 开始事务
            self.cursor.execute('BEGIN TRANSACTION')
            
            # 停用所有涉及该频道的配对
            self.cursor.execute('''
                UPDATE channel_pairs 
                SET is_active = 0 
                WHERE monitor_channel_id = ? OR forward_channel_id = ?
            ''', (channel_id, channel_id))
            
            # 停用频道
            self.cursor.execute('''
                UPDATE channels 
                SET is_active = 0 
                WHERE channel_id = ?
            ''', (channel_id,))
            
            # 提交事务
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            # 发生错误时回滚
            self.conn.rollback()
            logging.error(f"Error in remove_channel: {e}")
            return False

    def get_channels_by_type(self, channel_type: str, page: int = 1, per_page: int = 7) -> Dict[str, Any]:
        """分页获取指定类型的频道"""
        try:
            # 获取总数
            self.cursor.execute('''
                SELECT COUNT(*) FROM channels 
                WHERE channel_type = ? AND is_active = 1
            ''', (channel_type,))
            total = self.cursor.fetchone()[0]
            
            # 计算总页数
            total_pages = (total + per_page - 1) // per_page if total > 0 else 1
            
            # 确保页码有效
            page = max(1, min(page, total_pages))
            
            # 计算偏移量
            offset = (page - 1) * per_page
            
            # 获取当前页的数据
            self.cursor.execute('''
                SELECT channel_id, channel_name, channel_username, is_active 
                FROM channels 
                WHERE channel_type = ? AND is_active = 1
                ORDER BY added_date DESC
                LIMIT ? OFFSET ?
            ''', (channel_type, per_page, offset))
            
            channels = [{
                'channel_id': row[0],
                'channel_name': row[1],
                'channel_username': row[2],
                'is_active': row[3]
            } for row in self.cursor.fetchall()]
            
            return {
                'channels': channels,
                'total': total,
                'current_page': page,
                'total_pages': total_pages,
                'per_page': per_page
            }
        except sqlite3.Error as e:
            logging.error(f"Error in get_channels_by_type: {e}")
            return {
                'channels': [],
                'total': 0,
                'current_page': 1,
                'total_pages': 1,
                'per_page': per_page
            }

    def get_channel_pairs(self, page: int = 1, per_page: int = 7) -> Dict[str, Any]:
        """分页获取所有活跃的频道配对"""
        try:
            # 获取总数
            self.cursor.execute('''
                SELECT COUNT(*) 
                FROM channel_pairs cp
                JOIN channels m ON cp.monitor_channel_id = m.channel_id
                JOIN channels f ON cp.forward_channel_id = f.channel_id
                WHERE cp.is_active = 1
                AND m.is_active = 1
                AND f.is_active = 1
            ''')
            total = self.cursor.fetchone()[0]
            
            # 计算总页数
            total_pages = (total + per_page - 1) // per_page if total > 0 else 1
            
            # 确保页码有效
            page = max(1, min(page, total_pages))
            
            # 计算偏移量
            offset = (page - 1) * per_page
            
            # 获取当前页的数据
            self.cursor.execute('''
                SELECT 
                    cp.monitor_channel_id,
                    cp.forward_channel_id,
                    m.channel_name as monitor_name,
                    f.channel_name as forward_name,
                    cp.added_date
                FROM channel_pairs cp
                JOIN channels m ON cp.monitor_channel_id = m.channel_id
                JOIN channels f ON cp.forward_channel_id = f.channel_id
                WHERE cp.is_active = 1
                AND m.is_active = 1
                AND f.is_active = 1
                ORDER BY cp.added_date DESC
                LIMIT ? OFFSET ?
            ''', (per_page, offset))
            
            pairs = [{
                'monitor_channel_id': row[0],
                'forward_channel_id': row[1],
                'monitor_name': row[2],
                'forward_name': row[3],
                'added_date': row[4]
            } for row in self.cursor.fetchall()]
            
            return {
                'pairs': pairs,
                'total': total,
                'current_page': page,
                'total_pages': total_pages,
                'per_page': per_page
            }
        except sqlite3.Error as e:
            logging.error(f"Error in get_channel_pairs: {e}")
            return {
                'pairs': [],
                'total': 0,
                'current_page': 1,
                'total_pages': 1,
                'per_page': per_page
            }

    def get_unpaired_forward_channels(self, monitor_channel_id: int, 
                                    page: int = 1, per_page: int = 7) -> Dict[str, Any]:
        """获取未与指定监控频道配对的转发频道（带分页）"""
        try:
            # 获取总数
            self.cursor.execute('''
                SELECT COUNT(*)
                FROM channels c
                WHERE c.channel_type = 'FORWARD'
                AND c.is_active = 1
                AND c.channel_id NOT IN (
                    SELECT forward_channel_id 
                    FROM channel_pairs 
                    WHERE monitor_channel_id = ? 
                    AND is_active = 1
                )
            ''', (monitor_channel_id,))
            total = self.cursor.fetchone()[0]
            
            # 计算总页数
            total_pages = (total + per_page - 1) // per_page if total > 0 else 1
            
            # 确保页码有效
            page = max(1, min(page, total_pages))
            
            # 计算偏移量
            offset = (page - 1) * per_page
            
            # 获取数据
            self.cursor.execute('''
                SELECT c.channel_id, c.channel_name, c.channel_username
                FROM channels c
                WHERE c.channel_type = 'FORWARD'
                AND c.is_active = 1
                AND c.channel_id NOT IN (
                    SELECT forward_channel_id 
                    FROM channel_pairs 
                    WHERE monitor_channel_id = ? 
                    AND is_active = 1
                )
                ORDER BY c.added_date DESC
                LIMIT ? OFFSET ?
            ''', (monitor_channel_id, per_page, offset))
            
            channels = [{
                'channel_id': row[0],
                'channel_name': row[1],
                'channel_username': row[2]
            } for row in self.cursor.fetchall()]
            
            return {
                'channels': channels,
                'total': total,
                'current_page': page,
                'total_pages': total_pages,
                'per_page': per_page
            }
        except sqlite3.Error as e:
            logging.error(f"Error in get_unpaired_forward_channels: {e}")
            return {
                'channels': [],
                'total': 0,
                'current_page': 1,
                'total_pages': 1,
                'per_page': per_page
            }

    def get_forward_channels(self, monitor_channel_id: int, 
                           page: int = 1, per_page: int = 7) -> Dict[str, Any]:
        """获取监控频道对应的所有转发频道（带分页）"""
        try:
            # 获取总数
            self.cursor.execute('''
                SELECT COUNT(*) 
                FROM channels c
                JOIN channel_pairs cp ON c.channel_id = cp.forward_channel_id
                WHERE cp.monitor_channel_id = ? 
                AND cp.is_active = 1 
                AND c.is_active = 1
            ''', (monitor_channel_id,))
            total = self.cursor.fetchone()[0]
            
            # 计算总页数
            total_pages = (total + per_page - 1) // per_page if total > 0 else 1
            
            # 确保页码有效
            page = max(1, min(page, total_pages))
            
            # 计算偏移量
            offset = (page - 1) * per_page
            
            # 获取数据
            self.cursor.execute('''
                SELECT 
                    c.channel_id, 
                    c.channel_name, 
                    c.channel_username,
                    cp.added_date
                FROM channels c
                JOIN channel_pairs cp ON c.channel_id = cp.forward_channel_id
                WHERE cp.monitor_channel_id = ? 
                AND cp.is_active = 1 
                AND c.is_active = 1
                ORDER BY cp.added_date DESC
                LIMIT ? OFFSET ?
            ''', (monitor_channel_id, per_page, offset))
            
            channels = [{
                'channel_id': row[0],
                'channel_name': row[1],
                'channel_username': row[2],
                'added_date': row[3]
            } for row in self.cursor.fetchall()]
            
            return {
                'channels': channels,
                'total': total,
                'current_page': page,
                'total_pages': total_pages,
                'per_page': per_page
            }
        except sqlite3.Error as e:
            logging.error(f"Error in get_forward_channels: {e}")
            return {
                'channels': [],
                'total': 0,
                'current_page': 1,
                'total_pages': 1,
                'per_page': per_page
            }

    def get_all_forward_channels(self, monitor_channel_id: int) -> List[Dict[str, Any]]:
            """获取监控频道对应的所有活跃转发频道（不分页，用于消息转发）"""
            try:
                self.cursor.execute('''
                    SELECT 
                        c.channel_id,
                        c.channel_name,
                        c.channel_username,
                        cp.added_date
                    FROM channels c
                    JOIN channel_pairs cp ON c.channel_id = cp.forward_channel_id
                    WHERE cp.monitor_channel_id = ? 
                    AND cp.is_active = 1 
                    AND c.is_active = 1
                    ORDER BY cp.added_date ASC
                ''', (monitor_channel_id,))
                
                return [{
                    'channel_id': row[0],
                    'channel_name': row[1],
                    'channel_username': row[2],
                    'added_date': row[3]
                } for row in self.cursor.fetchall()]
                
            except sqlite3.Error as e:
                logging.error(f"Error in get_all_forward_channels: {e}")
                return []

    def add_channel_pair(self, monitor_channel_id: int, forward_channel_id: int) -> bool:
        """添加频道配对"""
        try:
            # 开始事务
            self.cursor.execute('BEGIN TRANSACTION')
            
            # 验证两个频道都存在且活跃
            self.cursor.execute('''
                SELECT COUNT(*) FROM channels 
                WHERE channel_id IN (?, ?) 
                AND is_active = 1
            ''', (monitor_channel_id, forward_channel_id))
            
            if self.cursor.fetchone()[0] != 2:
                raise sqlite3.Error("One or both channels are not active")
            
            # 检查配对是否已存在
            self.cursor.execute('''
                SELECT is_active 
                FROM channel_pairs 
                WHERE monitor_channel_id = ? 
                AND forward_channel_id = ?
            ''', (monitor_channel_id, forward_channel_id))
            
            existing_pair = self.cursor.fetchone()
            
            if existing_pair:
                if not existing_pair[0]:
                    # 如果配对存在但未激活，重新激活它
                    self.cursor.execute('''
                        UPDATE channel_pairs 
                        SET is_active = 1,
                            added_date = CURRENT_TIMESTAMP
                        WHERE monitor_channel_id = ? 
                        AND forward_channel_id = ?
                    ''', (monitor_channel_id, forward_channel_id))
            else:
                # 添加新配对
                self.cursor.execute('''
                    INSERT INTO channel_pairs 
                    (monitor_channel_id, forward_channel_id) 
                    VALUES (?, ?)
                ''', (monitor_channel_id, forward_channel_id))
            
            # 提交事务
            self.conn.commit()
            return True
            
        except sqlite3.Error as e:
            # 发生错误时回滚
            self.conn.rollback()
            logging.error(f"Error in add_channel_pair: {e}")
            return False

    def remove_channel_pair(self, monitor_channel_id: int, forward_channel_id: int) -> bool:
        """移除频道配对"""
        try:
            self.cursor.execute('''
                UPDATE channel_pairs 
                SET is_active = 0,
                    added_date = CURRENT_TIMESTAMP
                WHERE monitor_channel_id = ? 
                AND forward_channel_id = ?
                AND is_active = 1
            ''', (monitor_channel_id, forward_channel_id))
            
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error in remove_channel_pair: {e}")
            return False

    def get_channel_info(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """获取频道信息"""
        try:
            self.cursor.execute('''
                SELECT 
                    channel_id,
                    channel_name,
                    channel_username,
                    channel_type,
                    added_date,
                    is_active
                FROM channels 
                WHERE channel_id = ?
            ''', (channel_id,))
            
            row = self.cursor.fetchone()
            if row:
                return {
                    'channel_id': row[0],
                    'channel_name': row[1],
                    'channel_username': row[2],
                    'channel_type': row[3],
                    'added_date': row[4],
                    'is_active': row[5]
                }
            return None
        except sqlite3.Error as e:
            logging.error(f"Error in get_channel_info: {e}")
            return None

    def get_channel_stats(self, channel_id: int) -> Dict[str, Any]:
        """获取频道统计信息"""
        try:
            # 如果是监控频道，获取转发频道数量
            self.cursor.execute('''
                SELECT COUNT(*) 
                FROM channel_pairs 
                WHERE monitor_channel_id = ? 
                AND is_active = 1
            ''', (channel_id,))
            forward_count = self.cursor.fetchone()[0]

            # 如果是转发频道，获取监控频道数量
            self.cursor.execute('''
                SELECT COUNT(*) 
                FROM channel_pairs 
                WHERE forward_channel_id = ? 
                AND is_active = 1
            ''', (channel_id,))
            monitor_count = self.cursor.fetchone()[0]

            return {
                'forward_channel_count': forward_count,
                'monitor_channel_count': monitor_count
            }
        except sqlite3.Error as e:
            logging.error(f"Error in get_channel_stats: {e}")
            return {
                'forward_channel_count': 0,
                'monitor_channel_count': 0
            }

    def cleanup(self):
        """清理并关闭数据库连接"""
        if self.conn:
            try:
                # 可以在这里添加一些清理工作
                self.conn.commit()
            except sqlite3.Error as e:
                logging.error(f"Error during cleanup: {e}")
            finally:
                self.conn.close()

    def check_database_health(self) -> bool:
        """检查数据库健康状态"""
        try:
            # 检查表是否存在
            tables = ['channels', 'channel_pairs', 'user_preferences']
            for table in tables:
                self.cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
            
            # 检查索引是否存在
            self.cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='index' AND sql IS NOT NULL
            """)
            
            return True
        except sqlite3.Error as e:
            logging.error(f"Database health check failed: {e}")
            return False

    def optimize_database(self):
        """优化数据库"""
        try:
            self.cursor.executescript('''
                PRAGMA optimize;
                VACUUM;
                ANALYZE;
            ''')
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Database optimization failed: {e}")
            return False