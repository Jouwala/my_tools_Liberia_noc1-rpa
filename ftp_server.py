import os
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

# FTP 根目录 = 当前文件夹（运行脚本所在的工作目录）
ROOT_DIR = os.getcwd()

authorizer = DummyAuthorizer()
# 用户 ZTEEMS, 密码 DX, 根目录 = 当前文件夹, 读写权限(elradfmwMT)
authorizer.add_user("ZTEEMS", "DX", ROOT_DIR, perm="elradfmwMT")
# 用户 FINEBI, 密码 DX, 根目录 C:\FineBI6.0\webapps（仅当该目录存在时添加，避免启动崩溃）
finebi_dir = "C:\\FineBI6.0\\webapps"
if os.path.isdir(finebi_dir):
    authorizer.add_user("FINEBI", "DX", finebi_dir, perm="elradfmwMT")

handler = FTPHandler
handler.authorizer = authorizer
handler.passive_ports = range(60000, 60100)

server = FTPServer(("0.0.0.0", 21), handler)
print("FTP服务器已启动: 0.0.0.0:21")
print(f"根目录(当前文件夹): {ROOT_DIR}")
print("用户名: ZTEEMS | 密码: DX | 权限: 读写")
server.serve_forever()
