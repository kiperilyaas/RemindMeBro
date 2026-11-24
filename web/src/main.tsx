import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ui";
import { SessionProvider } from "./state/session";
import { ToastProvider } from "./state/toast";
import { setFavicon } from "./components/Brand";
import { trackScreenBottom } from "./lib/viewport";
import "./styles.css";

setFavicon();
trackScreenBottom();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <ToastProvider>
        <SessionProvider>
          <App />
        </SessionProvider>
      </ToastProvider>
    </ErrorBoundary>
  </StrictMode>,
);
