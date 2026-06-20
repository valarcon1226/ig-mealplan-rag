import React from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { StoreProvider, useStore } from './lib/store';
import Dashboard from './pages/Dashboard';
import Cookbook from './pages/Cookbook';
import Planner from './pages/Planner';
import Profile from './pages/Profile';
import RecipeImport from './pages/RecipeImport';
import { Home, Book, Calendar, User, PlusCircle } from 'lucide-react';
import { cn } from './lib/cn';
import { Toaster } from 'react-hot-toast';

function Navigation() {
  const location = useLocation();
  const navItems = [
    { path: '/', icon: Home, label: 'Dash' },
    { path: '/cookbook', icon: Book, label: 'Cookbook' },
    { path: '/import', icon: PlusCircle, label: 'Add Recipe' },
    { path: '/planner', icon: Calendar, label: 'Plan' },
    { path: '/profile', icon: User, label: 'Profile' },
  ];

  return (
    <nav className="fixed bottom-0 w-full bg-neutral-950 border-t border-neutral-800 pb-safe px-4 z-50">
      <div className="flex justify-between max-w-md mx-auto items-center h-16">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                "flex flex-col items-center justify-center w-full h-full space-y-1 transition-colors",
                isActive ? "text-orange-500" : "text-neutral-500 hover:text-neutral-300"
              )}
            >
              <item.icon className="h-5 w-5" />
              <span className="text-[10px] font-medium">{item.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

function PwaLayout({ children }: { children: React.ReactNode }) {
  const { isLoading } = useStore();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="text-orange-500 animate-pulse font-mono tracking-widest text-sm">LOADING...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-neutral-100 font-sans pb-20">
      {children}
      <Navigation />
      <Toaster position="bottom-center" toastOptions={{ style: { background: '#171717', color: '#fff', border: '1px solid #262626' } }} />
    </div>
  );
}

export default function App() {
  return (
    <StoreProvider>
      <BrowserRouter>
        <PwaLayout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/cookbook" element={<Cookbook />} />
            <Route path="/import" element={<RecipeImport />} />
            <Route path="/planner" element={<Planner />} />
            <Route path="/profile" element={<Profile />} />
          </Routes>
        </PwaLayout>
      </BrowserRouter>
    </StoreProvider>
  );
}
