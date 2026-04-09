# -*- coding: utf-8 -*-
"""
EditorMode 光标 API - 字符串版本使用示例

新增功能：
- set_editor_mode_cursor_by_name(name) - 通过名称设置光标
- get_editor_mode_cursor_name() - 获取当前光标名称
"""

import unreal

# ============================================================
# 1. 使用字符串名称设置光标（推荐）
# ============================================================

def example_cursor_by_name():
    """使用友好的字符串名称设置光标"""
    
    # 方式1：使用字符串（不区分大小写）
    unreal.ChameleonData.set_editor_mode_cursor_by_name("Hand")
    unreal.ChameleonData.set_editor_mode_cursor_by_name("hand")  # 也可以
    unreal.ChameleonData.set_editor_mode_cursor_by_name("HAND")  # 也可以
    
    # 获取当前光标名称
    current_name = unreal.ChameleonData.get_editor_mode_cursor_name()
    print(f"Current cursor: {current_name}")  # 输出: Current cursor: Hand
    
    # 尝试无效的名称（返回False并记录错误）
    success = unreal.ChameleonData.set_editor_mode_cursor_by_name("InvalidCursor")
    if not success:
        print("Failed to set cursor - invalid name")


# ============================================================
# 2. 所有可用的光标名称
# ============================================================

CURSOR_NAMES = {
    "None": "无光标",
    "Default": "默认（十字）",
    "TextEditBeam": "文本编辑I字光标",
    "ResizeLeftRight": "水平调整大小",
    "ResizeUpDown": "垂直调整大小",
    "ResizeSouthEast": "对角线调整大小↘",
    "ResizeSouthWest": "对角线调整大小↙",
    "CardinalCross": "十字移动",
    "Crosshairs": "十字准星",
    "Hand": "手形（可点击）",
    "GrabHand": "抓取手（张开）",
    "GrabHandClosed": "抓取手（握紧）",
    "SlashedCircle": "禁止符号🚫",
    "EyeDropper": "取色器",
    "Custom": "自定义",
}

def list_all_cursors():
    """列出所有可用的光标类型"""
    print("=== 可用的光标类型 ===")
    for name, description in CURSOR_NAMES.items():
        print(f"{name:20} - {description}")


# ============================================================
# 3. 在EditorMode事件中使用（字符串版本）
# ============================================================

def on_hover_with_names(input_ray):
    """使用字符串名称设置悬停光标"""
    # 执行射线检测
    hit = perform_raycast(input_ray)
    
    if hit:
        # 可交互物体 - 显示手形光标
        unreal.ChameleonData.set_editor_mode_cursor_by_name("Hand")
    else:
        # 无物体 - 显示默认光标
        unreal.ChameleonData.set_editor_mode_cursor_by_name("Default")

def on_mouse_down_with_names(input_ray):
    """按下鼠标时显示抓取光标"""
    unreal.ChameleonData.set_editor_mode_cursor_by_name("GrabHandClosed")

def on_mouse_up_with_names(input_ray):
    """释放鼠标时恢复手形光标"""
    unreal.ChameleonData.set_editor_mode_cursor_by_name("Hand")

def on_invalid_operation():
    """无效操作时显示禁止光标"""
    unreal.ChameleonData.set_editor_mode_cursor_by_name("SlashedCircle")


# ============================================================
# 4. 光标管理器（使用字符串名称）
# ============================================================

class CursorManager:
    """光标管理器 - 使用字符串名称"""
    
    @staticmethod
    def set_cursor(cursor_name):
        """
        设置光标
        
        Args:
            cursor_name (str): 光标名称
        
        Returns:
            bool: 是否设置成功
        """
        success = unreal.ChameleonData.set_editor_mode_cursor_by_name(cursor_name)
        if not success:
            unreal.log_warning(f"Failed to set cursor: {cursor_name}")
        return success
    
    @staticmethod
    def get_cursor():
        """获取当前光标名称"""
        return unreal.ChameleonData.get_editor_mode_cursor_name()
    
    @staticmethod
    def reset():
        """重置为默认光标"""
        return CursorManager.set_cursor("Default")
    
    # 预定义的光标快捷方法
    @staticmethod
    def show_hand():
        """显示手形光标"""
        return CursorManager.set_cursor("Hand")
    
    @staticmethod
    def show_grab():
        """显示抓取光标"""
        return CursorManager.set_cursor("GrabHandClosed")
    
    @staticmethod
    def show_crosshairs():
        """显示十字准星"""
        return CursorManager.set_cursor("Crosshairs")
    
    @staticmethod
    def show_forbidden():
        """显示禁止符号"""
        return CursorManager.set_cursor("SlashedCircle")
    
    @staticmethod
    def show_eyedropper():
        """显示取色器"""
        return CursorManager.set_cursor("EyeDropper")


# ============================================================
# 5. 实际使用示例
# ============================================================

def example_interactive_tool():
    """交互工具示例"""
    
    # 工具激活时设置十字准星
    CursorManager.show_crosshairs()
    
    # 检测到可交互物体
    CursorManager.show_hand()
    
    # 开始拖拽
    CursorManager.show_grab()
    
    # 结束拖拽
    CursorManager.show_hand()
    
    # 检测到无效操作
    CursorManager.show_forbidden()
    
    # 工具退出时重置
    CursorManager.reset()


def example_paint_tool():
    """绘制工具示例"""
    
    # 绘制模式 - 十字准星
    CursorManager.set_cursor("Crosshairs")
    
    # 取色模式 - 取色器
    CursorManager.set_cursor("EyeDropper")
    
    # 移动画布 - 手形
    CursorManager.set_cursor("Hand")


def example_with_validation():
    """带验证的示例"""
    
    cursor_to_set = "Hand"
    
    # 设置前验证
    if cursor_to_set in CURSOR_NAMES:
        success = CursorManager.set_cursor(cursor_to_set)
        if success:
            current = CursorManager.get_cursor()
            print(f"Cursor set to: {current}")
        else:
            print("Failed to set cursor")
    else:
        print(f"Invalid cursor name: {cursor_to_set}")


# ============================================================
# 6. 两种API对比
# ============================================================

def comparison_of_apis():
    """对比数字API和字符串API"""
    
    # 旧方式：使用数字（不直观）
    unreal.ChameleonData.set_editor_mode_cursor(3)  # 这是什么光标？
    
    # 新方式：使用字符串（直观易懂）
    unreal.ChameleonData.set_editor_mode_cursor_by_name("Hand")  # 一目了然
    
    # 旧方式：获取数字
    cursor_type = unreal.ChameleonData.get_editor_mode_cursor()  # 返回 3
    print(f"Cursor type: {cursor_type}")  # 需要查表才知道是什么
    
    # 新方式：获取名称
    cursor_name = unreal.ChameleonData.get_editor_mode_cursor_name()  # 返回 "Hand"
    print(f"Cursor name: {cursor_name}")  # 直接可读


# ============================================================
# 7. 辅助函数
# ============================================================

def perform_raycast(input_ray):
    """执行射线检测（示例）"""
    # 实际实现需要使用虚幻引擎的射线检测API
    return True  # 假设总是击中


def safe_set_cursor(cursor_name, fallback="Default"):
    """
    安全设置光标，失败时使用fallback
    
    Args:
        cursor_name (str): 要设置的光标名称
        fallback (str): 失败时的fallback光标
    """
    if not unreal.ChameleonData.set_editor_mode_cursor_by_name(cursor_name):
        unreal.ChameleonData.set_editor_mode_cursor_by_name(fallback)


# ============================================================
# 8. JSON配置示例
# ============================================================

"""
在EditorMode JSON配置中使用：

{
    "EditorModeName": "MyTool",
    "OnHover": "from cursor_name_api_example import CursorManager; CursorManager.show_hand()",
    "OnMouseDown": "from cursor_name_api_example import CursorManager; CursorManager.show_grab()",
    "OnMouseUp": "from cursor_name_api_example import CursorManager; CursorManager.show_hand()",
    "OnRelease": "from cursor_name_api_example import CursorManager; CursorManager.reset()"
}
"""


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=== EditorMode 光标 API - 字符串版本 ===")
    print()
    
    # 列出所有光标
    list_all_cursors()
    print()
    
    # 测试设置光标
    print("=== 测试光标设置 ===")
    CursorManager.show_hand()
    print(f"Current cursor: {CursorManager.get_cursor()}")
    
    CursorManager.show_crosshairs()
    print(f"Current cursor: {CursorManager.get_cursor()}")
    
    CursorManager.reset()
    print(f"Current cursor: {CursorManager.get_cursor()}")
    
    print()
    print("✓ 字符串API测试完成")
