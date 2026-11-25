"""Separate room equipment from facilities shared by the whole property."""
from accounts.text import normalize

SHARED_AMENITIES = (
    'Chỗ để xe', 'Camera an ninh', 'Khu phơi đồ', 'Máy giặt chung',
    'Sân chung', 'Cổng khóa an ninh', 'Khu sinh hoạt chung',
)
ALIASES = {normalize(name): name for name in SHARED_AMENITIES}
ALIASES.update({
    'bai de xe': 'Chỗ để xe', 'khu de xe': 'Chỗ để xe', 'khu de xe chung': 'Chỗ để xe',
    'cho de xe chung': 'Chỗ để xe', 'camera': 'Camera an ninh',
    'san phoi chung': 'Khu phơi đồ', 'khu phoi do chung': 'Khu phơi đồ',
    'cong khoa an toan': 'Cổng khóa an ninh',
})


def shared_name(value):
    return ALIASES.get(normalize(value.strip()))


def amenity_names(value):
    seen, result = set(), []
    for name in (value or '').replace('\n', ',').split(','):
        name = name.strip()
        key = normalize(name)
        if key and key not in seen:
            seen.add(key)
            result.append(name)
    return result


AMENITY_ICONS = {
    normalize(name): icon for name, icon in (
        ('Điều hòa', 'bi-snow'), ('Bình nóng lạnh', 'bi-thermometer-half'),
        ('Wifi', 'bi-wifi'), ('Gác lửng', 'bi-layers'), ('Nhà vệ sinh riêng', 'bi-droplet'),
        ('Khu bếp riêng', 'bi-fire'), ('Kệ bếp', 'bi-grid-3x2-gap'),
        ('Ban công', 'bi-sun'), ('Cửa sổ', 'bi-window'), ('Giường', 'bi-moon-stars'),
        ('Tủ quần áo', 'bi-door-closed'), ('Tủ lạnh', 'bi-box-seam'),
        ('Máy giặt', 'bi-arrow-repeat'), ('Chỗ để xe', 'bi-bicycle'),
        ('Camera an ninh', 'bi-camera-video'), ('Khu phơi đồ', 'bi-brightness-high'),
        ('Máy giặt chung', 'bi-arrow-repeat'), ('Sân chung', 'bi-tree'),
        ('Cổng khóa an ninh', 'bi-shield-lock'), ('Khu sinh hoạt chung', 'bi-people'),
    )
}


def amenity_tiles(names):
    """Keep configured names; icons never imply equipment that was not entered."""
    seen, tiles = set(), []
    for name in names:
        key = normalize(name)
        if key and key not in seen:
            seen.add(key)
            tiles.append({'name': name, 'icon': AMENITY_ICONS.get(key, 'bi-grid')})
    return tiles
