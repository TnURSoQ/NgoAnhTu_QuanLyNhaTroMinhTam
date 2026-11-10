import unicodedata


def normalize(text):
    """Bỏ dấu và chữ hoa để tìm kiếm: 'Nguyễn Văn Đạt' khớp với 'nguyen van dat'."""
    text = (text or '').replace('đ', 'd').replace('Đ', 'D')
    text = unicodedata.normalize('NFD', text)
    return ''.join(c for c in text if not unicodedata.combining(c)).lower()