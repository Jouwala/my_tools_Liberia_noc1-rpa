import os
path = r'd:\01_RPA\Task\my_app\backend\services\cn_ems\_probe_file.txt'
f = open(path, 'w', encoding='utf-8')
files = os.listdir(r'd:\01_RPA\Task\my_app\backend\services\cn_ems\templates')
for filename in files:
    f.write(repr(filename) + '\n')
f.close()
print('Written to %s' % path)