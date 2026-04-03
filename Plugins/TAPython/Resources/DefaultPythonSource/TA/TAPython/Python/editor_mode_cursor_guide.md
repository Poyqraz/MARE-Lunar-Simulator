# 虚幻引擎 EditorMode 光标 API 使用指南

## 概述

虚幻引擎提供了丰富的API来修改编辑器视窗中的鼠标光标样式。在您的EditorMode中，可以根据用户操作的不同动态更换鼠标样式，提供更好的用户体验和视觉反馈。

## API 函数

### 1. 设置光标
```python
unreal.ChameleonData.set_editor_mode_cursor(cursor_type: int) -> bool
```
设置EditorMode工具的光标类型。

**参数：**
- `cursor_type` (int): 光标类型，参考下面的光标类型列表

**返回值：**
- `bool`: 设置成功返回True，失败返回False

### 2. 获取光标
```python
unreal.ChameleonData.get_editor_mode_cursor() -> int
```
获取当前EditorMode工具的光标类型。

**返回值：**
- `int`: 当前光标类型值

## 可用的光标类型

基于 `EMouseCursor::Type` 枚举，以下是所有可用的光标类型：

| 值  | 名称            | 描述            | 使用场景             |
| --- | --------------- | --------------- | -------------------- |
| 0   | Default         | 默认箭头光标    | 通用操作             |
| 1   | None            | 隐藏光标        | 全屏模式、自定义渲染 |
| 2   | Crosshairs      | 十字准星        | 精确选择、绘制工具   |
| 3   | Hand            | 手型光标        | 可点击/可抓取对象    |
| 4   | GrabHand        | 张开的抓取手型  | 悬停在可拖拽对象上   |
| 5   | GrabHandClosed  | 闭合的抓取手型  | 拖拽操作进行中       |
| 6   | SlashedCircle   | 禁止/斜线圆圈   | 不可操作的区域       |
| 7   | EyeDropper      | 滴管工具        | 颜色选择、采样工具   |
| 8   | CardinalCross   | 主方向十字/移动 | 移动工具、平移操作   |
| 9   | Arrows          | 四向箭头        | 多方向移动           |
| 10  | ResizeLeftRight | 左右双向箭头    | 水平调整大小         |
| 11  | ResizeUpDown    | 上下双向箭头    | 垂直调整大小         |
| 12  | ResizeSouthEast | 东南方向箭头    | 对角线调整大小 ↘     |
| 13  | ResizeSouthWest | 西南方向箭头    | 对角线调整大小 ↙     |
| 14  | TextEditBeam    | I型文本光标     | 文本编辑             |

## 使用示例

### 基础用法

```python
import unreal

# 设置为十字准星光标
unreal.ChameleonData.set_editor_mode_cursor(2)  # Crosshairs

# 获取当前光标
current_cursor = unreal.ChameleonData.get_editor_mode_cursor()
print(f"当前光标: {current_cursor}")

# 重置为默认光标
unreal.ChameleonData.set_editor_mode_cursor(0)  # Default
```

### 在EditorMode事件中使用

#### 1. OnHover事件 - 悬停时改变光标

```python
# 在EditorMode JSON配置中
{
    "OnHover": "import unreal; hit = perform_raycast(%input_ray); unreal.ChameleonData.set_editor_mode_cursor(3) if hit else unreal.ChameleonData.set_editor_mode_cursor(0)"
}
```

#### 2. OnMouseDown事件 - 点击时改变光标

```python
# 在EditorMode JSON配置中
{
    "OnMouseDown": "import unreal; unreal.ChameleonData.set_editor_mode_cursor(5)"
}
```

#### 3. OnMouseUp事件 - 释放时恢复光标

```python
# 在EditorMode JSON配置中
{
    "OnMouseUp": "import unreal; unreal.ChameleonData.set_editor_mode_cursor(0)"
}
```

### 高级示例：根据操作模式改变光标

```python
import unreal

class EditorToolMode:
    """工具模式管理"""
    
    # 光标类型常量
    CURSOR_DEFAULT = 0
    CURSOR_CROSSHAIRS = 2
    CURSOR_HAND = 3
    CURSOR_GRAB_CLOSED = 5
    CURSOR_MOVE = 8
    CURSOR_RESIZE = 12
    
    def __init__(self):
        self.current_mode = 'select'
    
    def set_mode(self, mode):
        """设置工具模式并更新光标"""
        self.current_mode = mode
        self.update_cursor()
    
    def update_cursor(self):
        """根据当前模式更新光标"""
        cursor_map = {
            'select': self.CURSOR_DEFAULT,
            'paint': self.CURSOR_CROSSHAIRS,
            'grab': self.CURSOR_HAND,
            'move': self.CURSOR_MOVE,
            'resize': self.CURSOR_RESIZE,
        }
        
        cursor = cursor_map.get(self.current_mode, self.CURSOR_DEFAULT)
        unreal.ChameleonData.set_editor_mode_cursor(cursor)

# 使用示例
tool = EditorToolMode()
tool.set_mode('paint')  # 切换到绘制模式，光标变为十字准星
```

### 实战示例：对象选择工具

```python
import unreal

def on_hover_callback(input_ray):
    """鼠标悬停时的回调"""
    # 执行射线检测
    hit_result = raycast_from_input(input_ray)
    
    if hit_result and hit_result.get('actor'):
        actor = hit_result['actor']
        
        # 根据对象类型显示不同光标
        if is_locked(actor):
            # 被锁定的对象 - 禁止光标
            unreal.ChameleonData.set_editor_mode_cursor(6)
        elif is_selectable(actor):
            # 可选择的对象 - 手型光标
            unreal.ChameleonData.set_editor_mode_cursor(3)
        else:
            # 默认光标
            unreal.ChameleonData.set_editor_mode_cursor(0)
    else:
        # 没有悬停对象 - 默认光标
        unreal.ChameleonData.set_editor_mode_cursor(0)


def on_mouse_down_callback(input_ray):
    """鼠标按下时的回调"""
    hit_result = raycast_from_input(input_ray)
    
    if hit_result and hit_result.get('actor'):
        # 开始拖拽 - 闭合抓取手型
        unreal.ChameleonData.set_editor_mode_cursor(5)
        return True
    return False


def on_drag_callback(input_ray):
    """拖拽过程中的回调"""
    # 保持闭合抓取手型
    unreal.ChameleonData.set_editor_mode_cursor(5)


def on_mouse_up_callback(input_ray):
    """鼠标释放时的回调"""
    # 恢复默认光标
    unreal.ChameleonData.set_editor_mode_cursor(0)
```

## 完整的EditorMode配置示例

```json
{
    "EditorModeName": "CustomSelectionTool",
    "EditorModeIcon": "Icon.Tool",
    "EditorModePropertySetClass": "custom_tool_properties",
    
    "PythonInitCmd": "import sys; sys.path.append('D:/YourProject/Scripts');",
    
    "OnHover": "from my_tool import on_hover_callback; on_hover_callback(%input_ray)",
    "OnMouseDown": "from my_tool import on_mouse_down_callback; on_mouse_down_callback(%input_ray)",
    "OnDrag": "from my_tool import on_drag_callback; on_drag_callback(%input_ray)",
    "OnMouseUp": "from my_tool import on_mouse_up_callback; on_mouse_up_callback(%input_ray)"
}
```

## 最佳实践

### 1. 提供清晰的视觉反馈
- 在不同的交互状态使用不同的光标
- 悬停时显示预期的操作（如手型表示可点击）
- 拖拽时使用闭合的抓取手型

### 2. 保持一致性
- 在相似的操作中使用相同的光标
- 遵循常见的UI设计惯例

### 3. 性能考虑
- 避免在高频率调用的函数中频繁切换光标
- 只在状态真正改变时更新光标

### 4. 错误处理
```python
def safe_set_cursor(cursor_type):
    """安全地设置光标，带错误处理"""
    try:
        if 0 <= cursor_type <= 14:
            return unreal.ChameleonData.set_editor_mode_cursor(cursor_type)
        else:
            unreal.log_warning(f"Invalid cursor type: {cursor_type}")
            return False
    except Exception as e:
        unreal.log_error(f"Failed to set cursor: {str(e)}")
        return False
```

## 常见应用场景

### 场景1：绘制工具
```python
# 激活绘制模式
unreal.ChameleonData.set_editor_mode_cursor(2)  # Crosshairs
```

### 场景2：对象移动工具
```python
# 悬停在对象上
unreal.ChameleonData.set_editor_mode_cursor(8)  # CardinalCross
```

### 场景3：颜色采样工具
```python
# 激活滴管工具
unreal.ChameleonData.set_editor_mode_cursor(7)  # EyeDropper
```

### 场景4：缩放工具
```python
# 根据缩放方向选择光标
unreal.ChameleonData.set_editor_mode_cursor(10)  # ResizeLeftRight
# 或
unreal.ChameleonData.set_editor_mode_cursor(12)  # ResizeSouthEast
```

## 注意事项

1. **EditorMode必须处于激活状态**：光标设置只在EditorMode激活时有效
2. **光标类型范围**：有效的光标类型值为 0-25（部分值可能未使用）
3. **平台差异**：某些光标在不同操作系统上的显示可能略有不同
4. **优先级**：EditorMode的光标设置会覆盖默认的编辑器光标

## 调试技巧

```python
# 打印当前光标类型
current = unreal.ChameleonData.get_editor_mode_cursor()
unreal.log(f"Current cursor type: {current}")

# 测试所有光标类型
def test_all_cursors():
    """循环测试所有光标类型"""
    import time
    for i in range(15):
        unreal.ChameleonData.set_editor_mode_cursor(i)
        unreal.log(f"Cursor type: {i}")
        time.sleep(1)  # 暂停1秒观察效果
```

## 参考资源

- [Unreal Engine Slate UI Documentation](https://docs.unrealengine.com/en-US/ProgrammingAndScripting/Slate/index.html)
- [EMouseCursor Enum Reference](https://docs.unrealengine.com/en-US/API/Runtime/Core/Misc/EMouseCursor__Type/index.html)

---

**版本**: 1.3.0  
**日期**: 2026年1月14日  
**作者**: Huipeng Chen
