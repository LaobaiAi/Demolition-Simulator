# Third-Party Notices / 第三方依赖声明

本文件声明 XuanwuAI Demolition Simulator 运行与构建所依赖的第三方组件及其许可证。本项目自身以 MIT 许可发布（见 [LICENSE](LICENSE)）。

> 许可证信息以各依赖安装时自带的 METADATA / `package.json` 字段为准（2026-08-25 于本仓库 venv 与 node_modules 实测核对）；正式引用请以各上游仓库的 LICENSE 文件为准。未能直接查证的条目标注"见上游仓库许可文件"。

## Python 后端依赖（gateway/requirements.txt 及 CAIAO 求解器）

| 依赖 | 许可证 | 版权方 / 说明 |
|---|---|---|
| FastAPI | MIT | © Sebastian Ramirez / FastAPI 作者 |
| Starlette | BSD-3-Clause | Encode OSS Ltd.（FastAPI 传递依赖） |
| Uvicorn | BSD-3-Clause | Encode OSS Ltd. |
| mcp (MCP Python SDK) | MIT | Anthropic, PBC |
| caiao | 见上游仓库许可文件 | 项目专用包（CAIAO 协议 SDK 壳层） |
| Pydantic | MIT | © Samuel Colvin and contributors |
| python-socketio | MIT | © Miguel Grinberg |
| httpx | BSD-3-Clause | Encode OSS Ltd. |
| openai | Apache-2.0 | OpenAI |
| mem0ai | Apache-2.0 | mem0 开源项目 |
| pytest | MIT | Holger Krekel and the pytest-dev team |
| pytest-asyncio | Apache-2.0 | pytest-asyncio 贡献者 |
| PyYAML | MIT | © Ingy döt Net 与 Kirill Simonov（CI 依赖，`pip install pyyaml`） |
| OpenSeesPy | OpenSees 开源许可（研究/教育/内部使用免费；商业再分发需商业授权） | © Oregon State University（Dr. Minjie Zhu 等）；本地安装元数据引用定制 LICENSE.md，详见上游仓库 |
| anaStruct | GPL-3.0-or-later | © Ritchie Vink。注意：GPL 为 copyleft 许可，若对外分发本项目的组合制品，请评估 GPL 义务 |
| PyNite (pynitefea) | MIT | © Justin Stewart |

## 前端依赖（frontend/package.json）

| 依赖 | 许可证 | 版权方 / 说明 |
|---|---|---|
| Next.js (next) | MIT | 详见上游仓库（Vercel） |
| React (react / react-dom) | MIT | 详见上游仓库（Meta Platforms） |
| Three.js (three) | MIT | © mrdoob (Ricardo Cabello) 及贡献者 |
| @react-three/fiber | MIT | 详见上游仓库（pmndrs） |
| @react-three/drei | MIT | 详见上游仓库（pmndrs） |
| socket.io-client | MIT | 详见上游仓库（Socket.IO 团队） |
| TypeScript (typescript) | Apache-2.0 | © Microsoft Corp. |
| Vitest | MIT | 详见上游仓库（VoidZero / antfu） |
| Tailwind CSS (tailwindcss / @tailwindcss/postcss / @tailwindcss/typography) | MIT | 详见上游仓库（Tailwind Labs） |
| ESLint (eslint / eslint-config-next) | MIT | 详见上游仓库（ESLint / Vercel） |
| Recharts | MIT | © recharts group |
| cannon-es | MIT | 详见上游仓库 |
| web-ifc | MPL-2.0 | © web-ifc（IFC.js 项目） |
| lucide-react | ISC | © Eric Fennis |
| react-markdown / remark-gfm | MIT | 详见上游仓库 |
| clsx | MIT | 详见上游仓库 |
| tailwind-merge | MIT | 详见上游仓库 |
| class-variance-authority | Apache-2.0 | 详见上游仓库 |
| @base-ui/react | MIT | 详见上游仓库（MUI Base UI） |
| jsdom | MIT | 详见上游仓库 |
| shadcn | MIT | 详见上游仓库（shadcn/ui） |
| @testing-library/react | MIT | 详见上游仓库（Testing Library） |

## 外部工具（可选运行时，不随仓库分发）

| 工具 | 许可证 | 说明 |
|---|---|---|
| Abaqus / Abaqus CAE | 专有（Proprietary） | © Dassault Systèmes；需商业授权 |
| Unity Editor / Unity Engine | 专有（Proprietary） | © Unity Technologies；使用需遵守 Unity 许可条款（个人版免费，商业使用需订阅/授权） |
| Blender | GPL-2.0-or-later（含 Blender Foundation 的 Blender Exception） | © Blender Foundation。Blender 以 GPL v2+ 发布，并附带 Blender Foundation 的例外条款（允许以不同许可打包/分发随 Blender 分发的 Python 脚本与插件）；具体义务以 Blender 官方许可文本为准 |
| OpenSees (Windows 求解内核，OpenSeesPy 依赖) | OpenSees 开源许可（研究/教育/内部免费；商业再分发需商业授权） | 同上 OpenSeesPy 条目，版权归 Pacific Earthquake Engineering Research Center / Oregon State University 等 |

## 附注

- 许可类型来自各依赖安装元数据实测（Python：`*.dist-info/METADATA` 的 `License-Expression` / `License` 字段；前端：`node_modules/*/package.json` 的 `license` 字段）。
- 如对本清单有疑问或需要完整许可文本，请参阅各上游仓库的 LICENSE 文件。
