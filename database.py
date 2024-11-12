# db.py - 数据库处理
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

            CREATE INDEX IF NOT EXISTS idx_channels_type 
            ON channels(channel_type);
        ''')
        self.conn.commit()


    # 修改 Database 类

    def get_unpaired_forward_channels(self, monitor_channel_id: int, page: int = 1, per_page: int = 5) -> Dict[str, Any]:
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
            
            # 获取分页数据
            offset = (page - 1) * per_page
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
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page
            }
        except sqlite3.Error as e:
            logging.error(f"Error in get_unpaired_forward_channels: {e}")
            return {'channels': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 0}

    def get_forward_channels(self, monitor_channel_id: int, page: int = 1, per_page: int = 5) -> Dict[str, Any]:
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
            
            # 获取分页数据
            offset = (page - 1) * per_page
            self.cursor.execute('''
                SELECT c.channel_id, c.channel_name, c.channel_username
                FROM channels c
                JOIN channel_pairs cp ON c.channel_id = cp.forward_channel_id
                WHERE cp.monitor_channel_id = ? 
                AND cp.is_active = 1 
                AND c.is_active = 1
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
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page
            }
        except sqlite3.Error as e:
            logging.error(f"Error in get_forward_channels: {e}")
            return {'channels': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 0}
        # 在 Database 类中添加以下方法

# 在 Database 类中添加新方法

    def get_all_forward_channels(self, monitor_channel_id: int) -> List[Dict[str, Any]]:
        """获取监控频道对应的所有活跃转发频道（不分页）"""
        try:
            self.cursor.execute('''
                SELECT 
                    c.channel_id,
                    c.channel_name,
                    c.channel_username
                FROM channels c
                JOIN channel_pairs cp ON c.channel_id = cp.forward_channel_id
                WHERE cp.monitor_channel_id = ? 
                AND cp.is_active = 1 
                AND c.is_active = 1
            ''', (monitor_channel_id,))
            
            return [{
                'channel_id': row[0],
                'channel_name': row[1],
                'channel_username': row[2]
            } for row in self.cursor.fetchall()]
            
        except sqlite3.Error as e:
            logging.error(f"Database error in get_all_forward_channels: {e}")
            return []
        except Exception as e:
            logging.error(f"Unexpected error in get_all_forward_channels: {e}")
            return []


    def get_channel_pairs(self) -> List[Dict[str, Any]]:
        """获取所有活跃的频道配对"""
        try:
            self.cursor.execute('''
                SELECT 
                    cp.monitor_channel_id,
                    cp.forward_channel_id,
                    m.channel_name as monitor_name,
                    f.channel_name as forward_name
                FROM channel_pairs cp
                JOIN channels m ON cp.monitor_channel_id = m.channel_id
                JOIN channels f ON cp.forward_channel_id = f.channel_id
                WHERE cp.is_active = 1
                AND m.is_active = 1
                AND f.is_active = 1
            ''')
            
            return [{
                'monitor_channel_id': row[0],
                'forward_channel_id': row[1],
                'monitor_name': row[2],
                'forward_name': row[3]
            } for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Error in get_channel_pairs: {e}")
            return []

    def remove_channel_pair(self, monitor_channel_id: int, forward_channel_id: int) -> bool:
        """移除频道配对"""
        try:
            self.cursor.execute('''
                UPDATE channel_pairs 
                SET is_active = 0 
                WHERE monitor_channel_id = ? AND forward_channel_id = ?
            ''', (monitor_channel_id, forward_channel_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error in remove_channel_pair: {e}")
            return False

    def add_channel(self, channel_id: int, channel_name: str, 
                channel_username: Optional[str], channel_type: str) -> bool:
        """添加新频道"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO channels 
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
            # 停用配对
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
            
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error in remove_channel: {e}")
            return False

    def get_channels_by_type(self, channel_type: str, page: int = 1, per_page: int = 10) -> List[Dict[str, Any]]:
        """分页获取指定类型的频道"""
        try:
            offset = (page - 1) * per_page
            self.cursor.execute('''
                SELECT channel_id, channel_name, channel_username, is_active 
                FROM channels 
                WHERE channel_type = ? AND is_active = 1
                LIMIT ? OFFSET ?
            ''', (channel_type, per_page, offset))
            
            return [{
                'channel_id': row[0],
                'channel_name': row[1],
                'channel_username': row[2],
                'is_active': row[3]
            } for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Error in get_channels_by_type: {e}")
            return []

    def get_channel_count(self, channel_type: str) -> int:
        """获取指定类型的频道总数"""
        try:
            self.cursor.execute('''
                SELECT COUNT(*) 
                FROM channels 
                WHERE channel_type = ? AND is_active = 1
            ''', (channel_type,))
            return self.cursor.fetchone()[0]
        except sqlite3.Error as e:
            logging.error(f"Error in get_channel_count: {e}")
            return 0

    def add_channel_pair(self, monitor_channel_id: int, forward_channel_id: int) -> bool:
        """添加频道配对"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO channel_pairs 
                (monitor_channel_id, forward_channel_id) 
                VALUES (?, ?)
            ''', (monitor_channel_id, forward_channel_id))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logging.error(f"Error in add_channel_pair: {e}")
            return False

    def remove_channel_pair(self, monitor_channel_id: int, forward_channel_id: int) -> bool:
        """移除频道配对"""
        try:
            self.cursor.execute('''
                UPDATE channel_pairs 
                SET is_active = 0 
                WHERE monitor_channel_id = ? AND forward_channel_id = ?
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
                SELECT * FROM channels WHERE channel_id = ?
            ''', (channel_id,))
            row = self.cursor.fetchone()
            if row:
                return {
                    'channel_id': row[0],
                    'channel_name': row[1],
                    'channel_username': row[2],
                    'channel_type': row[3],
                    'is_active': row[5]
                }
            return None
        except sqlite3.Error as e:
            logging.error(f"Error in get_channel_info: {e}")
            return None

    def cleanup(self):
        """清理并关闭数据库连接"""
        if self.conn:
            self.conn.close()
