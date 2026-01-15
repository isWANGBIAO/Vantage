from PIL import Image

img = Image.open('icon.png')
img.save('icon.ico')
print("图标已成功转换为 icon.ico")
