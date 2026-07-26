"""
用户管理模块
提供用户注册、登录验证、权限控制等功能
"""

import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timedelta
from functools import wraps


class UserManager:
    """用户管理类"""
    
    def __init__(self, db_path):
        """
        初始化用户管理器
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._init_database()
    
    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_database(self):
        """初始化数据库，创建用户表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 创建用户表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT UNIQUE,
                full_name TEXT,
                role TEXT DEFAULT 'user',
                avatar_url TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')
        
        # 创建会话表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_username ON users (username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_session_token ON user_sessions (session_token)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON user_sessions (user_id)')
        
        # 创建默认管理员账户（如果不存在）
        cursor.execute('SELECT COUNT(*) FROM users WHERE role = "admin"')
        if cursor.fetchone()[0] == 0:
            # 创建默认管理员账户：admin / admin123
            default_password = self._hash_password('admin123')
            cursor.execute('''
                INSERT INTO users (username, password_hash, email, full_name, role)
                VALUES (?, ?, ?, ?, ?)
            ''', ('admin', default_password, 'admin@example.com', 'System Administrator', 'admin'))
        
        conn.commit()
        conn.close()
    
    def _hash_password(self, password):
        """
        对密码进行哈希处理
        
        Args:
            password: 原始密码
            
        Returns:
            哈希后的密码
        """
        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
        return f"{salt}${password_hash.hex()}"
    
    def _verify_password(self, password, password_hash):
        """
        验证密码
        
        Args:
            password: 原始密码
            password_hash: 存储的哈希密码
            
        Returns:
            bool: 密码是否正确
        """
        try:
            salt, hash_value = password_hash.split('$')
            new_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
            return new_hash.hex() == hash_value
        except Exception:
            return False
    
    def _generate_session_token(self):
        """生成会话令牌"""
        return secrets.token_urlsafe(32)
    
    def register_user(self, username, password, email=None, full_name=None, role='user'):
        """
        注册新用户
        
        Args:
            username: 用户名
            password: 密码
            email: 邮箱
            full_name: 全名
            role: 角色
            
        Returns:
            dict: {'success': bool, 'message': str, 'user_id': int}
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # 检查用户名是否已存在
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            if cursor.fetchone():
                return {'success': False, 'message': '用户名已存在'}
            
            # 检查邮箱是否已存在
            if email:
                cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
                if cursor.fetchone():
                    return {'success': False, 'message': '邮箱已被注册'}
            
            # 创建用户
            password_hash = self._hash_password(password)
            cursor.execute('''
                INSERT INTO users (username, password_hash, email, full_name, role)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, password_hash, email, full_name, role))
            
            conn.commit()
            user_id = cursor.lastrowid
            
            return {'success': True, 'message': '注册成功', 'user_id': user_id}
        
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': f'注册失败：{str(e)}'}
        
        finally:
            conn.close()
    
    def login(self, username, password, remember_me=False):
        """
        用户登录
        
        Args:
            username: 用户名
            password: 密码
            remember_me: 是否记住登录状态
            
        Returns:
            dict: {'success': bool, 'message': str, 'session_token': str, 'user': dict}
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # 查找用户
            cursor.execute('''
                SELECT id, username, password_hash, email, full_name, role, avatar_url, is_active, last_login
                FROM users
                WHERE username = ?
            ''', (username,))
            
            user_row = cursor.fetchone()
            
            if not user_row:
                return {'success': False, 'message': '用户名或密码错误'}
            
            # 验证密码
            if not self._verify_password(password, user_row['password_hash']):
                return {'success': False, 'message': '用户名或密码错误'}
            
            # 检查账户是否激活
            if not user_row['is_active']:
                return {'success': False, 'message': '账户已被禁用'}
            
            # 更新最后登录时间
            cursor.execute('UPDATE users SET last_login = ? WHERE id = ?', (datetime.now(), user_row['id']))
            conn.commit()
            
            # 创建会话
            session_token = self._generate_session_token()
            expires_at = datetime.now() + timedelta(days=30 if remember_me else 7)
            
            cursor.execute('''
                INSERT INTO user_sessions (user_id, session_token, expires_at)
                VALUES (?, ?, ?)
            ''', (user_row['id'], session_token, expires_at))
            
            conn.commit()
            
            # 返回用户信息（不包含密码）
            user_info = {
                'id': user_row['id'],
                'username': user_row['username'],
                'email': user_row['email'],
                'full_name': user_row['full_name'],
                'role': user_row['role'],
                'avatar_url': user_row['avatar_url']
            }
            
            return {
                'success': True,
                'message': '登录成功',
                'session_token': session_token,
                'user': user_info
            }
        
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': f'登录失败：{str(e)}'}
        
        finally:
            conn.close()
    
    def logout(self, session_token):
        """
        用户登出
        
        Args:
            session_token: 会话令牌
            
        Returns:
            bool: 是否成功登出
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM user_sessions WHERE session_token = ?', (session_token,))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def get_user_by_session(self, session_token):
        """
        通过会话令牌获取用户信息
        
        Args:
            session_token: 会话令牌
            
        Returns:
            dict: 用户信息，失败返回 None
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # 查询会话
            cursor.execute('''
                SELECT user_id, expires_at
                FROM user_sessions
                WHERE session_token = ?
            ''', (session_token,))
            
            session = cursor.fetchone()
            
            if not session:
                return None
            
            # 检查会话是否过期
            if datetime.now() > datetime.strptime(session['expires_at'], '%Y-%m-%d %H:%M:%S.%f'):
                # 删除过期会话
                cursor.execute('DELETE FROM user_sessions WHERE session_token = ?', (session_token,))
                conn.commit()
                return None
            
            # 查询用户信息
            cursor.execute('''
                SELECT id, username, email, full_name, role, avatar_url, is_active
                FROM users
                WHERE id = ?
            ''', (session['user_id'],))
            
            user_row = cursor.fetchone()
            
            if not user_row or not user_row['is_active']:
                return None
            
            return {
                'id': user_row['id'],
                'username': user_row['username'],
                'email': user_row['email'],
                'full_name': user_row['full_name'],
                'role': user_row['role'],
                'avatar_url': user_row['avatar_url']
            }
        
        except Exception:
            return None
        finally:
            conn.close()
    
    def update_user(self, user_id, **kwargs):
        """
        更新用户信息
        
        Args:
            user_id: 用户 ID
            **kwargs: 要更新的字段
            
        Returns:
            dict: {'success': bool, 'message': str}
        """
        allowed_fields = ['email', 'full_name', 'avatar_url']
        update_data = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not update_data:
            return {'success': False, 'message': '没有可更新的字段'}
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # 构建更新语句
            set_clause = ', '.join([f"{field} = ?" for field in update_data.keys()])
            values = list(update_data.values()) + [user_id]
            
            cursor.execute(f'''
                UPDATE users
                SET {set_clause}, updated_at = ?
                WHERE id = ?
            ''', [*values, datetime.now(), user_id])
            
            conn.commit()
            return {'success': True, 'message': '更新成功'}
        
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': f'更新失败：{str(e)}'}
        
        finally:
            conn.close()
    
    def change_password(self, user_id, old_password, new_password):
        """
        修改密码
        
        Args:
            user_id: 用户 ID
            old_password: 旧密码
            new_password: 新密码
            
        Returns:
            dict: {'success': bool, 'message': str}
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # 获取当前密码
            cursor.execute('SELECT password_hash FROM users WHERE id = ?', (user_id,))
            user_row = cursor.fetchone()
            
            if not user_row:
                return {'success': False, 'message': '用户不存在'}
            
            # 验证旧密码
            if not self._verify_password(old_password, user_row['password_hash']):
                return {'success': False, 'message': '旧密码错误'}
            
            # 更新密码
            new_password_hash = self._hash_password(new_password)
            cursor.execute('''
                UPDATE users
                SET password_hash = ?, updated_at = ?
                WHERE id = ?
            ''', (new_password_hash, datetime.now(), user_id))
            
            conn.commit()
            return {'success': True, 'message': '密码修改成功'}
        
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': f'密码修改失败：{str(e)}'}
        
        finally:
            conn.close()
    
    def get_all_users(self):
        """
        获取所有用户列表
        
        Returns:
            list: 用户列表
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT id, username, email, full_name, role, is_active, created_at, last_login
                FROM users
                ORDER BY created_at DESC
            ''')
            
            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row['id'],
                    'username': row['username'],
                    'email': row['email'],
                    'full_name': row['full_name'],
                    'role': row['role'],
                    'is_active': bool(row['is_active']),
                    'created_at': row['created_at'],
                    'last_login': row['last_login']
                })
            
            return users
        
        except Exception:
            return []
        finally:
            conn.close()
    
    def delete_user(self, user_id):
        """
        删除用户
        
        Args:
            user_id: 用户 ID
            
        Returns:
            dict: {'success': bool, 'message': str}
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # 不允许删除管理员账户
            cursor.execute('SELECT role FROM users WHERE id = ?', (user_id,))
            user_row = cursor.fetchone()
            
            if not user_row:
                return {'success': False, 'message': '用户不存在'}
            
            if user_row['role'] == 'admin':
                return {'success': False, 'message': '不能删除管理员账户'}
            
            cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
            conn.commit()
            return {'success': True, 'message': '删除成功'}
        
        except Exception as e:
            conn.rollback()
            return {'success': False, 'message': f'删除失败：{str(e)}'}
        
        finally:
            conn.close()
    
    def cleanup_expired_sessions(self):
        """清理过期的会话"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM user_sessions WHERE expires_at < ?', (datetime.now(),))
            conn.commit()
            return cursor.rowcount
        except Exception:
            conn.rollback()
            return 0
        finally:
            conn.close()


def login_required(f):
    """
    登录验证装饰器
    用于 Flask 路由，要求用户必须登录
    """
    from flask import request, jsonify
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not session_token:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        user_manager = getattr(decorated_function, 'user_manager', None)
        if not user_manager:
            return jsonify({'success': False, 'message': '服务器配置错误'}), 500
        
        user = user_manager.get_user_by_session(session_token)
        if not user:
            return jsonify({'success': False, 'message': '登录已过期'}), 401
        
        request.current_user = user  # type: ignore[attr-defined]
        return f(*args, **kwargs)
    
    return decorated_function


def admin_required(f):
    """
    管理员验证装饰器
    用于 Flask 路由，要求用户必须是管理员
    """
    from flask import request, jsonify
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.headers.get('Authorization', '').replace('Bearer ', '')
        
        if not session_token:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        user_manager = getattr(decorated_function, 'user_manager', None)
        if not user_manager:
            return jsonify({'success': False, 'message': '服务器配置错误'}), 500
        
        user = user_manager.get_user_by_session(session_token)
        if not user:
            return jsonify({'success': False, 'message': '登录已过期'}), 401
        
        if user.get('role') != 'admin':
            return jsonify({'success': False, 'message': '权限不足'}), 403
        
        request.current_user = user  # type: ignore[attr-defined]
        return f(*args, **kwargs)
    
    return decorated_function
