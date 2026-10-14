import React, { ErrorInfo, ReactNode } from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import './styles.css';
import App from './shell.tsx';

const client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 20_000 } } });
class ErrorBoundary extends React.Component<{children:ReactNode},{failed:boolean}> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error:Error,_info:ErrorInfo) { /* Error details stay in the browser; never show internals to the user. */ }
  render() { return this.state.failed ? <main className="error-screen"><h1>Something went wrong</h1><p>Please reload the page. Your account and care data remain on the server.</p></main> : this.props.children; }
}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ErrorBoundary><QueryClientProvider client={client}><BrowserRouter><App /></BrowserRouter></QueryClientProvider></ErrorBoundary></React.StrictMode>);
