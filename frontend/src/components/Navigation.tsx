import React from 'react';
import { MessageCircle, Map, Brain } from 'lucide-react';

interface NavigationProps {
  currentView: 'chat' | 'world' | 'memory';
  onViewChange: (view: 'chat' | 'world' | 'memory') => void;
}

const Navigation: React.FC<NavigationProps> = ({ currentView, onViewChange }) => {
  const navItems = [
    {
      id: 'chat' as const,
      label: 'Dream Weaver',
      icon: MessageCircle,
      description: 'Converse with your mystical guide'
    },
    {
      id: 'world' as const,
      label: 'Inner World',
      icon: Map,
      description: 'Explore your constellation of experiences'
    },
    {
      id: 'memory' as const,
      label: 'Memory Sanctum',
      icon: Brain,
      description: 'Manage your sacred memories'
    }
  ];

  return (
    <nav className="flex justify-center px-2">
      <div className="cosmic-card p-1 sm:p-2 flex space-x-1 sm:space-x-2 w-full max-w-md sm:max-w-none">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentView === item.id;

          return (
            <button
              key={item.id}
              onClick={() => onViewChange(item.id)}
              className={`
                flex flex-col items-center px-2 sm:px-6 py-2 sm:py-4 rounded-lg transition-all duration-300 flex-1 sm:flex-none
                ${isActive
                  ? 'bg-antara-500/20 text-antara-400 mystical-glow'
                  : 'text-cosmic-400 hover:text-cosmic-200 hover:bg-cosmic-700/50'
                }
              `}
              title={item.description}
            >
              <Icon className={`w-4 h-4 sm:w-6 sm:h-6 mb-1 sm:mb-2 ${isActive ? 'animate-pulse' : ''}`} />
              <span className="text-xs sm:text-sm font-medium text-center leading-tight">{item.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
};

export default Navigation;
