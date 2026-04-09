"""
EditorMode 光标 API - 快速参考

快速复制使用的代码片段
"""

# ============================================================
# 基础使用
# ============================================================

import unreal

# 设置光标
unreal.ChameleonData.set_editor_mode_cursor(2)  # 十字准星

# 获取当前光标
cursor = unreal.ChameleonData.get_editor_mode_cursor()

# 重置为默认
unreal.ChameleonData.set_editor_mode_cursor(0)


# ============================================================
# 光标类型常量
# ============================================================

DEFAULT = 0              # 默认箭头
NONE = 1                 # 隐藏
CROSSHAIRS = 2           # 十字准星 ✛
HAND = 3                 # 手型 ✋
GRAB_HAND = 4            # 张开抓取手 🖐
GRAB_HAND_CLOSED = 5     # 闭合抓取手 ✊
SLASHED_CIRCLE = 6       # 禁止 🚫
EYE_DROPPER = 7          # 滴管 💧
CARDINAL_CROSS = 8       # 移动十字 ✢
ARROWS = 9               # 四向箭头 ⬌
RESIZE_LEFT_RIGHT = 10   # 水平调整 ↔
RESIZE_UP_DOWN = 11      # 垂直调整 ↕
RESIZE_SE = 12           # 东南对角 ↘
RESIZE_SW = 13           # 西南对角 ↙
TEXT_EDIT_BEAM = 14      # 文本编辑 I


# ============================================================
# OnHover 事件使用
# ============================================================

# 在 JSON 配置中
{
    "OnHover": "import unreal; unreal.ChameleonData.set_editor_mode_cursor(3)"
}

# 或者在 Python 脚本中
def on_hover(input_ray):
    unreal.ChameleonData.set_editor_mode_cursor(3)  # Hand


# ============================================================
# OnMouseDown/Up 事件使用
# ============================================================

# 在 JSON 配置中
{
    "OnMouseDown": "import unreal; unreal.ChameleonData.set_editor_mode_cursor(5)",
    "OnMouseUp": "import unreal; unreal.ChameleonData.set_editor_mode_cursor(0)"
}


# ============================================================
# 完整示例：拖拽操作
# ============================================================

def on_mouse_down(input_ray):
    """按下鼠标"""
    unreal.ChameleonData.set_editor_mode_cursor(5)  # 闭合抓取手

def on_drag(input_ray):
    """拖拽中"""
    unreal.ChameleonData.set_editor_mode_cursor(5)  # 保持闭合抓取手

def on_mouse_up(input_ray):
    """释放鼠标"""
    unreal.ChameleonData.set_editor_mode_cursor(0)  # 恢复默认


# ============================================================
# 完整示例：根据对象类型改变光标
# ============================================================

def on_hover_smart(input_ray):
    """智能悬停：根据对象类型改变光标"""
    hit = raycast(input_ray)
    
    if hit:
        if is_locked(hit.actor):
            unreal.ChameleonData.set_editor_mode_cursor(6)  # 禁止
        elif is_moveable(hit.actor):
            unreal.ChameleonData.set_editor_mode_cursor(8)  # 移动
        else:
            unreal.ChameleonData.set_editor_mode_cursor(3)  # 手型
    else:
        unreal.ChameleonData.set_editor_mode_cursor(0)  # 默认


# ============================================================
# 工具模式管理
# ============================================================

class ToolModeManager:
    CURSORS = {
        'select': 0,    # 默认
        'paint': 2,     # 十字准星
        'move': 8,      # 移动十字
        'scale': 12,    # 对角调整
        'rotate': 9,    # 四向箭头
        'sample': 7,    # 滴管
    }
    
    @staticmethod
    def set_mode(mode):
        cursor = ToolModeManager.CURSORS.get(mode, 0)
        unreal.ChameleonData.set_editor_mode_cursor(cursor)

# 使用
ToolModeManager.set_mode('paint')


# ============================================================
# 实用工具函数
# ============================================================

def safe_set_cursor(cursor_type):
    """安全设置光标"""
    if 0 <= cursor_type <= 14:
        return unreal.ChameleonData.set_editor_mode_cursor(cursor_type)
    return False

def reset_cursor():
    """重置光标"""
    return unreal.ChameleonData.set_editor_mode_cursor(0)


# ============================================================
# EditorMode JSON 完整配置示例
# ============================================================

EXAMPLE_JSON_CONFIG = """
{
    "EditorModeName": "MyCustomTool",
    "EditorModeIcon": "Icon.Tool",
    "EditorModePropertySetClass": "my_tool_properties",
    
    "PythonInitCmd": "import sys; sys.path.append('D:/Scripts');",
    
    "OnHover": "import unreal; hit = raycast(%input_ray); unreal.ChameleonData.set_editor_mode_cursor(3 if hit else 0)",
    "OnMouseDown": "import unreal; unreal.ChameleonData.set_editor_mode_cursor(5)",
    "OnDrag": "import unreal; unreal.ChameleonData.set_editor_mode_cursor(5)",
    "OnMouseUp": "import unreal; unreal.ChameleonData.set_editor_mode_cursor(0)"
}
"""
