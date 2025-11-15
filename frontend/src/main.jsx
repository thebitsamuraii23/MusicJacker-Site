import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';

const mountNode = document.getElementById('reactbits-root');

if (mountNode) {
  const initialLang = window.reactbitsInitialLang || document.documentElement.lang || 'en';
  const data = window.reactbitsData || {};

  ReactDOM.createRoot(mountNode).render(
    <React.StrictMode>
      <App initialLang={initialLang} data={data} />
    </React.StrictMode>
  );
}
