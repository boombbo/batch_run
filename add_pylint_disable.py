# pylint: disable-all
import os
import sys

# 获取当前脚本所在目录（项目根目录的假设路径）
script_dir = os.path.dirname(os.path.abspath(__file__))

# 将脚本目录添加到环境变量 PYTHONPATH 中
sys.path.insert(0, script_dir)

# 项目根目录路径（假设脚本在项目根目录中）
root_dir = script_dir

# 遍历项目中的所有 Python 文件
for subdir, _, files in os.walk(root_dir):
    for file in files:
        if file.endswith(".py"):
            file_path = os.path.join(subdir, file)
            try:
                with open(file_path, "r+", encoding="utf-8") as f:
                    lines = f.readlines()

                    # 如果文件的第一行已经是 pylint 注释，更新它
                    if lines and lines[0].startswith("# pylint: disable-all"):
                        lines[0] = "# pylint: disable-all\n"
                    else:
                        # 如果没有，添加 pylint 注释作为第一行
                        lines.insert(0, "# pylint: disable-all\n")
                    
                    # 重写文件内容
                    f.seek(0)
                    f.writelines(lines)
                    f.truncate()
                    
                print(f"已更新文件: {file_path}")  # 打印已更新的文件路径
            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {e}")  # 捕获并打印错误信息

print("所有文件已更新。")

# 打印项目根目录路径和脚本路径（用于调试）
print(f"项目根目录: {root_dir}")
print(f"脚本路径: {script_dir}")
