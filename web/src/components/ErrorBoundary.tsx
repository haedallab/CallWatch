import { Component, type ReactNode } from "react";

/** Keeps one broken screen from blanking the whole app; offers a recovery path. */
export default class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidUpdate(prev: { resetKey?: string }) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="banner err" role="alert">
        <div style={{ flex: 1 }}><b>이 화면을 그리는 중 문제가 생겼습니다.</b>
          <div className="small" style={{ marginTop: 4 }}>{this.state.error.message}</div></div>
        <button className="btn sm" onClick={() => this.setState({ error: null })}>다시 그리기</button>
        <button className="btn sm" onClick={() => location.reload()}>새로고침</button>
      </div>
    );
  }
}
