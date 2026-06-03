"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  onError: () => void;
}

interface State {
  hasError: boolean;
}

export class WebGLErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    console.warn("[WebGLErrorBoundary] WebGL crashed, falling back to SVG:", error.message);
    this.props.onError();
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
          <p className="text-sm">⚠️ WebGL 渲染不可用，已自动切换到 SVG 模式</p>
          <p className="text-xs opacity-60">当前环境或 GPU 不支持 WebGL</p>
        </div>
      );
    }
    return this.props.children;
  }
}
