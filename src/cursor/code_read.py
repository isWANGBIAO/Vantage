def read_code(file_path):
    """
    读取代码文件内容。
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()
