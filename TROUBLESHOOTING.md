# XuanwuAI Demolition Simulator — 疑难杂症记录

## 1. OpenSees 在 Windows 上不可用

**现象**: `import openseespy.opensees` 报 `DLL load failed while importing opensees: 找不到指定的模块`

**根因**: openseespywin 的 `.pyd` 文件链接了 `python312.dll`，但系统安装的是 Python 3.13。DLL 版本不匹配导致加载失败。

**解决方案**:
1. 安装 `uv`（Python 版本管理器）：
   ```powershell
   powershell -Command "irm https://astral.sh/uv/install.ps1 | iex"
   ```
2. 用 uv 安装 Python 3.12：
   ```bash
   uv python install 3.12
   ```
3. 重建 venv：
   ```bash
   rm -rf venv
   uv venv --python 3.12 venv
   uv pip install -r requirements.txt --python venv/Scripts/python.exe
   uv pip install openseespy openseespywin anastruct --python venv/Scripts/python.exe
   ```

**参考**: StructureClaw 项目（https://github.com/structureclaw/structureclaw）同样使用 uv + Python 3.12 解决此问题。

---

## 2. TextContent JSON 序列化错误

**现象**: `Object of type TextContent is not JSON serializable`

**根因**: CAIAO SDK 的 `TextContent` 类型（Pydantic BaseModel）不能被 `json.dumps` 直接序列化。多个路径都会触发：
- WebSocket `send_json` 内部调用 `json.dumps`
- CAIAO server 返回的 `result.content` 包含 TextContent 对象
- OpenAI SDK 返回的 content 可能是 `list[ContentBlock]` 而非 `str`

**解决方案**（三层防护）：

1. **全局 monkey-patch** (`gateway/main.py` 顶部)：
```python
import json
_original_dumps = json.dumps

def _patched_dumps(obj, **kwargs):
    def _walk(o):
        if o is None or isinstance(o, (bool, int, float, str)):
            return o
        if isinstance(o, (list, tuple)):
            return [_walk(i) for i in o]
        if isinstance(o, dict):
            return {str(k): _walk(v) for k, v in o.items()}
        if hasattr(o, "text"):
            return str(o.text)
        if hasattr(o, "model_dump"):
            return _walk(o.model_dump())
        return str(o)
    return _original_dumps(_walk(obj), **kwargs)

json.dumps = _patched_dumps
```

2. **WebSocket 安全发送** (`gateway/main.py`):
```python
def _sanitize_for_json(obj):
    # 递归清洗非 JSON 类型
    ...

async def _safe_send(data):
    await websocket.send_json(_sanitize_for_json(data))
```

3. **LLM 内容规范化** (`gateway/llm_engine.py`):
```python
def _normalize_content(content):
    if content is None: return None
    if isinstance(content, str): return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if hasattr(block, "text"): parts.append(block.text)
            elif isinstance(block, dict) and "text" in block: parts.append(block["text"])
            elif isinstance(block, str): parts.append(block)
        return "".join(parts) if parts else None
    return str(content)
```

4. **CAIAO Hub 去除非序列化字段** (`caiao` pip package, `CAIAOClientHub._trim_pipeline_result`):
```python
# 不返回 result.content (包含 TextContent 对象)
return {"result": texts[0] if len(texts) == 1 else texts}
```

---

## 3. DeepSeek 思维链 400 错误

**现象**: `Error code: 400 - 'The reasoning_content in the thinking mode must be passed back to the API'`

**根因**: DeepSeek 的 thinking mode 在每个 assistant 消息中返回 `reasoning_content` 字段，要求客户端在下一轮对话中原样回传。

**解决方案** (`gateway/llm_engine.py` + `gateway/agent_loop.py`):

```python
# llm_engine.py: 提取 reasoning_content
reasoning = getattr(message, "reasoning_content", None)
if reasoning:
    response["reasoning_content"] = reasoning

# agent_loop.py: 回传 reasoning_content
assistant_msg = {
    "role": "assistant",
    "content": response.get("content"),
    "tool_calls": [...],
}
if response.get("reasoning_content"):
    assistant_msg["reasoning_content"] = response["reasoning_content"]
messages.append(assistant_msg)
```

---

## 4. FloatingToolbar SSR 水合不匹配

**现象**: React 水合时报错，服务端和客户端渲染不一致

**根因**: FloatingToolbar 在 `useState` 初始化时调用 `localStorage.getItem()`，服务端无此 API。

**解决方案**：CSS 变量方案
```typescript
// 服务端和客户端都渲染相同的初始值
<div style={{
  left: 'var(--toolbar-x, 16px)',
  top: 'var(--toolbar-y, 16px)',
}}>

// useEffect 在客户端设置 CSS 变量（不触发重渲染）
useEffect(() => {
  const saved = loadPosition();  // localStorage
  el.style.setProperty('--toolbar-x', `${saved.x}px`);
  el.style.setProperty('--toolbar-y', `${saved.y}px`);
}, []);
```

同时用 `useRef` 跟踪拖拽位置（直接 DOM 操作），避免拖拽时频繁重渲染。

---

## 5. LLM 设置切换模型丢失 API Key

**现象**: 切换模型后 API Key 和 Base URL 被清空

**根因**: 保存用 `{api_key, base_url}` 键名，加载用 `{apiKey, baseUrl}` 键名，key 不匹配。

**解决方案**: 统一键名 + 按模型记忆
```typescript
// 以 model 为 key 存储 profile
const PROFILES_KEY = 'xuanwu_llm_profiles';

function saveProfiles(profiles: Record<string, Profile>) {
  localStorage.setItem(PROFILES_KEY, JSON.stringify(profiles));
}

const handleModelChange = (newModel: string) => {
  const profile = profiles[newModel];
  if (profile) {
    setLlmApiKey(profile.api_key);
    setLlmBaseUrl(profile.base_url);
  } else {
    setLlmApiKey('');
    setLlmBaseUrl('');
  }
};
```

---

## 6. Chat 窗口被长 AI 回复撑开

**现象**: AI 输出很长时，聊天区域占据整个屏幕，可视化面板不可见

**解决方案**: `max-h-[360px] overflow-y-auto` 限制 AI 消息气泡高度，tool result JSON 截断到 200 字符。

---

## 7. 多个 Gateway 进程残留导致端口冲突

**现象**: `Address already in use` 或旧代码仍在运行

**解决方案**:
```powershell
powershell -Command "Get-Process python | Stop-Process -Force"
```

---

## 8. Unity Editor 许可证激活

**现象**: Unity batch mode 报 `No valid Unity Editor license found`

**解决方案**:
1. 打开 Unity Hub → 登录 Unity 账号
2. Settings → Licenses → Add → Get a free personal license
3. 激活后即可使用

---

## 9. uv venv 无 pip

**现象**: `venv/Scripts/pip.exe` 不存在

**根因**: uv 创建的 venv 不包含 pip

**解决方案**: 始终用 `uv pip install` 替代 `pip install`
```bash
uv pip install <package> --python venv/Scripts/python.exe
```

---

## 10. 多个 Python 版本共存 + openseespywin 兼容性

**核心原则**:
- openseespywin 的 `.pyd` 绑定特定 Python 版本（`python312.dll`）
- 必须用 Python 3.12，3.13 不行
- 用 `uv` 管理 Python 版本，不要手动下载安装包
- `uv python install 3.12` 自动处理下载和安装

---

*最后更新: 2026-05-23*
