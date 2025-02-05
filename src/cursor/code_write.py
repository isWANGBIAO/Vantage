def write_code(file_path, code):
    """
    将修改后的代码写回文件。
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(code)
    print(f"已修改代码并保存至: {file_path}")
