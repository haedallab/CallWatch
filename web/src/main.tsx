import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import "./styles.css";
import { AppProvider } from "./lib/store";
import { AuthProvider } from "./lib/auth";
import Layout from "./components/Layout";
import Home from "./pages/Home";
import { Empty, PageSkeleton } from "./components/ui";

const Portfolio = lazy(() => import("./pages/Portfolio"));
const Company = lazy(() => import("./pages/Company"));
const Transcript = lazy(() => import("./pages/Transcript"));
const Ask = lazy(() => import("./pages/Ask"));
const Method = lazy(() => import("./pages/Method"));
const Present = lazy(() => import("./pages/Present"));
const Account = lazy(() => import("./pages/Account"));

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <AppProvider>
         <AuthProvider>
          <Suspense fallback={<PageSkeleton />}>
            <Routes>
              <Route path="present" element={<Present />} />
              <Route element={<Layout />}>
                <Route index element={<Home />} />
                <Route path="portfolio" element={<Portfolio />} />
                <Route path="company" element={<Company />} />
                <Route path="company/:ticker" element={<Company />} />
                <Route path="transcript" element={<Transcript />} />
                <Route path="ask" element={<Ask />} />
                <Route path="method" element={<Method />} />
                <Route path="account" element={<Account />} />
                <Route path="*" element={<Empty title="페이지를 찾을 수 없습니다" body="위쪽 메뉴에서 이동하거나 ⌘K로 검색하세요." />} />
              </Route>
            </Routes>
          </Suspense>
          <Toaster position="top-center" richColors closeButton />
         </AuthProvider>
        </AppProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
