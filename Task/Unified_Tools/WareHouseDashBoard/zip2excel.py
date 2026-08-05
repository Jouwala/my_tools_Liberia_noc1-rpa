import os
import pandas as pd
import zipfile
from pathlib import Path
from io import BytesIO


def process_eflow_files():
    # 1. 定义路径
    # 自动获取当前系统的下载文件夹路径
    download_path = Path.home() / "Downloads"
    # 定义输出的目标文件夹
    output_base_path = Path.cwd() / "data"
    output_base_path.mkdir(exist_ok=True)

    # 2. 定义处理配置：(文件名前缀, 输出文件名)
    tasks = [
        ("eflow-sp-inbound-", "inband_details.xlsx"),
        ("eflow-sp-outbound-", "outband_details.xlsx"),
        ("eflow-sp-material-", "inventory_details.xlsx")
    ]

    for prefix, output_name in tasks:
        print(f"正在处理前缀为 [{prefix}] 的文件...")

        # 获取所有匹配的 zip 文件，并按修改时间倒序排列
        zip_files = sorted(
            [f for f in download_path.glob(f"{prefix}*.zip")],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )

        if not zip_files:
            print(f"  - 未找到匹配 {prefix} 的压缩包，跳过。")
            continue

        # 保留最新的一个，删除其他的
        latest_zip = zip_files[0]
        others = zip_files[1:]

        for old_file in others:
            try:
                old_file.unlink()
                print(f"  - 已删除旧文件: {old_file.name}")
            except Exception as e:
                print(f"  - 删除失败 {old_file.name}: {e}")

        # 3. 读取最新的压缩包内的 Excel 文件
        all_df = []
        try:
            with zipfile.ZipFile(latest_zip, 'r') as z:
                # 过滤出压缩包内的所有 Excel 文件
                excel_files = [f for f in z.namelist() if
                               f.endswith(('.xlsx', '.xls')) and not f.startswith('__MACOSX')]

                for excel_file in excel_files:
                    with z.open(excel_file) as f:
                        # 使用 BytesIO 读取内存中的数据，避免频繁读写磁盘
                        df = pd.read_excel(BytesIO(f.read()))
                        all_df.append(df)

            # 4. 合并并输出
            if all_df:
                merged_df = pd.concat(all_df, ignore_index=True)
                output_path = output_base_path / output_name
                merged_df.to_excel(output_path, index=False)
                print(f"  - 成功！合并后的文件保存至: {output_path}")
            else:
                print(f"  - 警告：压缩包 {latest_zip.name} 中未发现有效的 Excel 文件。")

        except Exception as e:
            print(f"  - 处理压缩包时出错: {e}")


if __name__ == "__main__":
    process_eflow_files()
