# -*- coding: utf-8 -*-
"""
EditorMode光标设置示例

此示例演示如何在EditorMode中根据用户操作动态改变鼠标光标样式

作者: Huipeng Chen
日期: 2026年1月14日
"""

import unreal

# 可用的光标类型（对应EMouseCursor::Type枚举）
class CursorType:
    """
    虚幻引擎支持的光标类型
    """
    Default = 0                # 默认箭头光标
    None_ = 1                  # 无光标（隐藏）
    Crosshairs = 2             # 十字准星
    Hand = 3                   # 手型光标
    GrabHand = 4               # 抓取手型光标
    GrabHandClosed = 5         # 关闭的抓取手型光标
    SlashedCircle = 6          # 禁止/斜线圆圈
    EyeDropper = 7             # 滴管工具
    CardinalCross = 8          # 主方向十字（移动光标）
    Arrows = 9                 # 四向箭头
    ResizeLeftRight = 10       # 左右调整大小
    ResizeUpDown = 11          # 上下调整大小
    ResizeSouthEast = 12       # 东南方向调整大小
    ResizeSouthWest = 13       # 西南方向调整大小
    TextEditBeam = 14          # 文本编辑I型光标
    


class EditorModeCursorManager:
    """EditorMode光标管理器"""
    
    @staticmethod
    def set_cursor(cursor_type):
        """
        设置EditorMode的光标类型
        
        Args:
            cursor_type (int): 光标类型，参考CursorType类
            
        Returns:
            bool: 是否设置成功
        """
        return unreal.ChameleonData.set_editor_mode_cursor(cursor_type)
    
    @staticmethod
    def get_cursor():
        """
        获取当前EditorMode的光标类型
        
        Returns:
            int: 当前光标类型
        """
        return unreal.ChameleonData.get_editor_mode_cursor()
    
    @staticmethod
    def reset_cursor():
        """重置光标为默认样式"""
        return EditorModeCursorManager.set_cursor(CursorType.Default)


# === 使用示例 ===

def example_basic_usage():
    """基础用法示例"""
    print("=== 基础光标设置示例 ===")
    
    # 设置为十字准星光标
    if EditorModeCursorManager.set_cursor(CursorType.Crosshairs):
        print("光标已设置为十字准星")
    
    # 获取当前光标类型
    current = EditorModeCursorManager.get_cursor()
    print(f"当前光标类型: {current}")
    
    # 重置为默认光标
    EditorModeCursorManager.reset_cursor()
    print("光标已重置为默认")


def example_hover_cursor():
    """悬停时改变光标的示例"""
    print("=== 悬停改变光标示例 ===")
    
    # 这个函数可以在OnHover事件中调用
    # 当鼠标悬停在不同类型的对象上时显示不同的光标
    
    def on_hover(input_ray):
        """在OnHover事件中调用此函数"""
        # 执行射线检测
        hit_result = perform_raycast(input_ray)
        
        if hit_result.get('hit'):
            actor = hit_result.get('actor')
            if actor:
                # 根据Actor类型设置不同的光标
                if 'StaticMesh' in actor.get_class().get_name():
                    EditorModeCursorManager.set_cursor(CursorType.Hand)
                elif 'Light' in actor.get_class().get_name():
                    EditorModeCursorManager.set_cursor(CursorType.EyeDropper)
                else:
                    EditorModeCursorManager.set_cursor(CursorType.Crosshairs)
        else:
            # 没有悬停在物体上时使用默认光标
            EditorModeCursorManager.reset_cursor()
    
    print("在OnHover事件中调用on_hover函数来根据悬停对象改变光标")


def example_drag_cursor():
    """拖拽操作时改变光标的示例"""
    print("=== 拖拽操作光标示例 ===")
    
    is_dragging = False
    
    def on_mouse_down(input_ray):
        """鼠标按下时"""
        global is_dragging
        is_dragging = True
        # 开始拖拽时显示抓取光标
        EditorModeCursorManager.set_cursor(CursorType.GrabHandClosed)
        print("开始拖拽，显示抓取光标")
    
    def on_drag(input_ray):
        """拖拽中"""
        if is_dragging:
            # 拖拽中保持抓取光标
            EditorModeCursorManager.set_cursor(CursorType.GrabHandClosed)
    
    def on_mouse_up(input_ray):
        """鼠标释放时"""
        global is_dragging
        is_dragging = False
        # 结束拖拽时恢复默认光标
        EditorModeCursorManager.reset_cursor()
        print("结束拖拽，恢复默认光标")
    
    print("在鼠标事件中调用相应函数来根据拖拽状态改变光标")


def example_context_cursor():
    """根据上下文改变光标的高级示例"""
    print("=== 上下文相关光标示例 ===")
    
    # 工具状态
    tool_mode = 'select'  # 'select', 'move', 'rotate', 'scale', 'paint'
    
    def update_cursor_by_mode():
        """根据工具模式更新光标"""
        cursor_map = {
            'select': CursorType.Default,
            'move': CursorType.CardinalCross,
            'rotate': CursorType.Arrows,
            'scale': CursorType.ResizeSouthEast,
            'paint': CursorType.Crosshairs,
        }
        
        cursor = cursor_map.get(tool_mode, CursorType.Default)
        EditorModeCursorManager.set_cursor(cursor)
        print(f"工具模式: {tool_mode}, 光标类型: {cursor}")
    
    # 模拟不同模式
    for mode in ['select', 'move', 'rotate', 'scale', 'paint']:
        tool_mode = mode
        update_cursor_by_mode()


def example_conditional_cursor():
    """条件判断光标示例"""
    print("=== 条件判断光标示例 ===")
    
    def on_hover_with_condition(input_ray):
        """根据条件显示不同光标"""
        hit_result = perform_raycast(input_ray)
        
        if hit_result.get('hit'):
            actor = hit_result.get('actor')
            
            # 检查是否可以编辑
            if can_edit_actor(actor):
                EditorModeCursorManager.set_cursor(CursorType.Hand)
                print("可编辑对象 - 显示手型光标")
            else:
                EditorModeCursorManager.set_cursor(CursorType.SlashedCircle)
                print("不可编辑对象 - 显示禁止光标")
        else:
            EditorModeCursorManager.reset_cursor()


# === 辅助函数 ===

def perform_raycast(input_ray):
    """
    执行射线检测（示例实现）
    
    Args:
        input_ray: InputDeviceRay对象
        
    Returns:
        dict: 包含hit结果的字典
    """
    # 这里应该实现真正的射线检测逻辑
    # 示例返回
    return {
        'hit': False,
        'actor': None,
        'location': None,
        'normal': None
    }


def can_edit_actor(actor):
    """
    检查Actor是否可以编辑（示例实现）
    
    Args:
        actor: 要检查的Actor
        
    Returns:
        bool: 是否可编辑
    """
    if not actor:
        return False
    
    # 示例逻辑：检查Actor是否被锁定
    # return not actor.is_actor_locked()
    return True


# === 在EditorMode JSON配置中使用 ===
"""
在您的EditorMode JSON配置文件中，可以这样使用：

{
    "EditorModeName": "MyEditorMode",
    "EditorModePropertySetClass": "my_tool_properties",
    "OnHover": "from editor_mode_cursor_example import EditorModeCursorManager, CursorType; EditorModeCursorManager.set_cursor(CursorType.Crosshairs)",
    "OnMouseDown": "from editor_mode_cursor_example import EditorModeCursorManager, CursorType; EditorModeCursorManager.set_cursor(CursorType.GrabHandClosed)",
    "OnMouseUp": "from editor_mode_cursor_example import EditorModeCursorManager; EditorModeCursorManager.reset_cursor()"
}
"""


if __name__ == '__main__':
    print("EditorMode光标设置API示例")
    print("=" * 50)
    
    # 运行所有示例
    example_basic_usage()
    print("\n")
    
    example_hover_cursor()
    print("\n")
    
    example_drag_cursor()
    print("\n")
    
    example_context_cursor()
    print("\n")
    
    example_conditional_cursor()
    print("\n")
    
    print("=" * 50)
    print("提示：在实际使用时，请在EditorMode的事件回调中调用这些函数")
