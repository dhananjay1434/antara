import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { MessageCircle, Map, Brain, Sparkles } from 'lucide-react';
import ChatWindow from './components/ChatWindow';
import WorldMap from './components/WorldMap';
import MemorySanctum from './components/MemorySanctum';
import Navigation from './components/Navigation';
import { userAPI } from './services/api';

function App() {
  const [currentView, setCurrentView] = useState<'chat' | 'world' | 'memory'>('chat');
  const [userId, setUserId] = useState<string>('');
  const [isInitialized, setIsInitialized] = useState(false);

  useEffect(() => {
    initializeUser();
  }, []);

  const initializeUser = async () => {
    try {
      // Generate or get user ID from localStorage
      let storedUserId = localStorage.getItem('antara_user_id');
      if (!storedUserId) {
        storedUserId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        localStorage.setItem('antara_user_id', storedUserId);
      }

      // Create user if doesn't exist
      await userAPI.createUser(storedUserId, `User ${storedUserId.split('_')[1]}`);
      setUserId(storedUserId);
      setIsInitialized(true);
    } catch (error) {
      console.error('Failed to initialize user:', error);
      // Still set initialized to true to allow the app to work
      setIsInitialized(true);
    }
  };

  if (!isInitialized) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <Sparkles className="w-12 h-12 text-antara-500 mx-auto mb-4 animate-spin" />
          <p className="text-cosmic-300">Awakening your inner world...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-cosmic-900 via-cosmic-800 to-cosmic-700">
      <div className="container mx-auto px-4 py-6 max-w-6xl">
        {/* Header */}
        <header className="text-center mb-8">
          <div className="flex items-center justify-center mb-4">
            <Sparkles className="w-8 h-8 text-antara-500 mr-3" />
            <h1 className="text-4xl font-bold bg-gradient-to-r from-antara-400 to-antara-600 bg-clip-text text-transparent">
              Antarā
            </h1>
          </div>
          <p className="text-cosmic-300 text-lg">Your Inner World Awaits</p>
        </header>

        {/* Navigation */}
        <Navigation currentView={currentView} onViewChange={setCurrentView} />

        {/* Main Content */}
        <main className="mt-8">
          {currentView === 'chat' && <ChatWindow userId={userId} />}
          {currentView === 'world' && <WorldMap userId={userId} />}
          {currentView === 'memory' && <MemorySanctum userId={userId} />}
        </main>

        {/* Footer */}
        <footer className="text-center mt-12 text-cosmic-400 text-sm">
          <p>✨ Where thoughts become constellations and memories find their sanctuary ✨</p>
        </footer>
      </div>
    </div>
  );
}

export default App;
