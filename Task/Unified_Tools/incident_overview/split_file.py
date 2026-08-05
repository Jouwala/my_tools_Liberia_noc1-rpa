import math

def split_html_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        total_lines = len(lines)
        if total_lines == 0:
            print("文件内容为空")
            return

        # 计算每一份的大小（向上取整确保覆盖所有行）
        chunk_size = math.ceil(total_lines / 4)

        for i in range(4):
            start = i * chunk_size
            end = min((i + 1) * chunk_size, total_lines)
            
            output_filename = f'index_part_{i+1}.html'
            with open(output_filename, 'w', encoding='utf-8') as f_out:
                f_out.writelines(lines[start:end])
            
            print(f"已生成: {output_filename} (第 {start+1} 行 到 第 {end} 行)")

    except FileNotFoundError:
        print("错误：未找到 index.html 文件")
    except Exception as e:
        print(f"发生错误: {e}")

if __name__ == "__main__":
    path = r'D:\Dong\pythonproject2026\Tools\Unified_Tools\incident_overview\index.html'
    split_html_file(path)
