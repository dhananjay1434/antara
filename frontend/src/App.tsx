import { useState, useEffect } from 'react';
import { Sparkles } from 'lucide-react';
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
    <div className="min-h-screen bg-gradient-to-br from-cosmic-900 via-cosmic-800 to-cosmic-700 overflow-x-hidden">
      <div className="container mx-auto px-2 sm:px-4 py-3 sm:py-6 max-w-6xl">
        {/* Header */}
        <header className="text-center mb-4 sm:mb-8">
          <div className="flex items-center justify-center mb-2 sm:mb-4">
            <Sparkles className="w-6 h-6 sm:w-8 sm:h-8 text-antara-500 mr-2 sm:mr-3" />
            <h1 className="text-2xl sm:text-4xl font-bold bg-gradient-to-r from-antara-400 to-antara-600 bg-clip-text text-transparent">
              Antarā
            </h1>
          </div>
          <p className="text-cosmic-300 text-sm sm:text-lg">Your Inner World Awaits</p>
        </header>

        {/* Navigation */}
        <Navigation currentView={currentView} onViewChange={setCurrentView} />

        {/* Main Content */}
        <main className="mt-4 sm:mt-8">
          {currentView === 'chat' && <ChatWindow userId={userId} />}
          {currentView === 'world' && <WorldMap userId={userId} />}
          {currentView === 'memory' && <MemorySanctum userId={userId} />}
        </main>

        {/* Footer */}
        <footer className="text-center mt-6 sm:mt-12 text-cosmic-400 text-xs sm:text-sm px-4">
          <p>✨ Where thoughts become constellations and memories find their sanctuary ✨</p>
        </footer>
      </div>
    </div>
  );
}

export default App;
