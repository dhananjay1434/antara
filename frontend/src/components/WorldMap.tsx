import React, { useState, useEffect } from 'react';
import { Star, Sparkles, Calendar } from 'lucide-react';
import { worldAPI, WorldNode } from '../services/api';

interface WorldMapProps {
  userId: string;
}

const WorldMap: React.FC<WorldMapProps> = ({ userId }) => {
  const [worldNodes, setWorldNodes] = useState<WorldNode[]>([]);
  const [selectedNode, setSelectedNode] = useState<WorldNode | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    loadWorldNodes();
  }, [userId]);

  const loadWorldNodes = async () => {
    try {
      setIsLoading(true);
      const nodes = await worldAPI.getWorldNodes(userId);
      setWorldNodes(nodes);
    } catch (error) {
      console.error('Failed to load world nodes:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const generateStarPosition = (index: number, total: number) => {
    // Create a spiral constellation pattern
    const angle = (index * 137.5) * (Math.PI / 180); // Golden angle for natural distribution
    const radius = Math.sqrt(index) * 40 + 100; // Spiral outward
    const centerX = 50;
    const centerY = 50;
    
    const x = centerX + (radius * Math.cos(angle)) / 8;
    const y = centerY + (radius * Math.sin(angle)) / 8;
    
    // Keep within bounds
    return {
      left: `${Math.max(5, Math.min(95, x))}%`,
      top: `${Math.max(5, Math.min(95, y))}%`
    };
  };

  if (isLoading) {
    return (
      <div className="cosmic-card p-8 text-center">
        <Sparkles className="w-12 h-12 text-antara-500 mx-auto mb-4 animate-spin" />
        <p className="text-cosmic-300">Mapping your inner constellation...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="cosmic-card p-6">
        <div className="flex items-center mb-4">
          <Star className="w-6 h-6 text-antara-500 mr-3" />
          <div>
            <h2 className="text-2xl font-bold text-cosmic-100">Your Inner World</h2>
            <p className="text-cosmic-400">A constellation of your journey through thoughts and feelings</p>
          </div>
        </div>
        
        {worldNodes.length > 0 && (
          <div className="text-sm text-cosmic-300">
            <span className="text-antara-400 font-semibold">{worldNodes.length}</span> stars illuminate your inner sky
          </div>
        )}
      </div>

      {/* Constellation Map */}
      <div className="cosmic-card p-6">
        {worldNodes.length === 0 ? (
          <div className="text-center py-16">
            <Star className="w-16 h-16 text-cosmic-600 mx-auto mb-4" />
            <h3 className="text-xl font-semibold text-cosmic-300 mb-2">Your constellation awaits</h3>
            <p className="text-cosmic-400 max-w-md mx-auto">
              Share meaningful thoughts with the Dream Weaver, and watch as stars begin to appear in your inner world, 
              each one representing a moment of connection and understanding.
            </p>
          </div>
        ) : (
          <div className="relative h-96 bg-gradient-to-br from-cosmic-900/50 to-cosmic-800/50 rounded-xl overflow-hidden">
            {/* Background stars effect */}
            <div className="absolute inset-0 opacity-30">
              {Array.from({ length: 50 }).map((_, i) => (
                <div
                  key={i}
                  className="absolute w-1 h-1 bg-cosmic-400 rounded-full animate-pulse"
                  style={{
                    left: `${Math.random() * 100}%`,
                    top: `${Math.random() * 100}%`,
                    animationDelay: `${Math.random() * 3}s`,
                    animationDuration: `${2 + Math.random() * 2}s`
                  }}
                />
              ))}
            </div>

            {/* World Nodes as Stars */}
            {worldNodes.map((node, index) => {
              const position = generateStarPosition(index, worldNodes.length);
              const isSelected = selectedNode?.id === node.id;
              
              return (
                <button
                  key={node.id}
                  className={`absolute transform -translate-x-1/2 -translate-y-1/2 transition-all duration-300 ${
                    isSelected ? 'scale-150 z-10' : 'hover:scale-125 z-0'
                  }`}
                  style={position}
                  onClick={() => setSelectedNode(isSelected ? null : node)}
                  title={node.title}
                >
                  <div className={`relative ${isSelected ? 'animate-pulse' : ''}`}>
                    <Star 
                      className={`w-6 h-6 ${
                        isSelected 
                          ? 'text-antara-400 fill-antara-400' 
                          : 'text-antara-500 fill-antara-500/70 hover:text-antara-400'
                      } transition-colors duration-200`}
                    />
                    {isSelected && (
                      <div className="absolute inset-0 animate-ping">
                        <Star className="w-6 h-6 text-antara-400 opacity-75" />
                      </div>
                    )}
                  </div>
                </button>
              );
            })}

            {/* Connection lines between nearby stars */}
            <svg className="absolute inset-0 w-full h-full pointer-events-none opacity-20">
              {worldNodes.map((node, index) => {
                if (index === 0) return null;
                const currentPos = generateStarPosition(index, worldNodes.length);
                const prevPos = generateStarPosition(index - 1, worldNodes.length);
                
                return (
                  <line
                    key={`line-${index}`}
                    x1={currentPos.left}
                    y1={currentPos.top}
                    x2={prevPos.left}
                    y2={prevPos.top}
                    stroke="#ec4899"
                    strokeWidth="1"
                    strokeOpacity="0.3"
                  />
                );
              })}
            </svg>
          </div>
        )}
      </div>

      {/* Selected Node Details */}
      {selectedNode && (
        <div className="cosmic-card p-6 mystical-glow">
          <div className="flex items-start justify-between mb-4">
            <div className="flex items-center">
              <Star className="w-5 h-5 text-antara-400 mr-2 fill-antara-400" />
              <h3 className="text-xl font-semibold text-cosmic-100">{selectedNode.title}</h3>
            </div>
            <div className="flex items-center text-cosmic-400 text-sm">
              <Calendar className="w-4 h-4 mr-1" />
              {formatDate(selectedNode.created_at)}
            </div>
          </div>
          
          <p className="text-cosmic-200 leading-relaxed">{selectedNode.summary}</p>
          
          <button
            onClick={() => setSelectedNode(null)}
            className="mt-4 text-antara-400 hover:text-antara-300 text-sm transition-colors duration-200"
          >
            Close
          </button>
        </div>
      )}

      {/* Legend */}
      {worldNodes.length > 0 && (
        <div className="cosmic-card p-4">
          <div className="flex items-center justify-center space-x-6 text-sm text-cosmic-400">
            <div className="flex items-center">
              <Star className="w-4 h-4 text-antara-500 fill-antara-500 mr-2" />
              <span>Moments of Understanding</span>
            </div>
            <div className="flex items-center">
              <div className="w-4 h-0.5 bg-antara-500/30 mr-2"></div>
              <span>Connections Through Time</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default WorldMap;
