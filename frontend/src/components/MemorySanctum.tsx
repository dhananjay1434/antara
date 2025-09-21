import React, { useState, useEffect } from 'react';
import { Brain, Trash2, Shield, AlertTriangle, Calendar, Sparkles } from 'lucide-react';
import { memoryAPI, Memory } from '../services/api';

interface MemorySanctumProps {
  userId: string;
}

const MemorySanctum: React.FC<MemorySanctumProps> = ({ userId }) => {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [deletingMemoryId, setDeletingMemoryId] = useState<number | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<number | null>(null);

  useEffect(() => {
    loadMemories();
  }, [userId]);

  const loadMemories = async () => {
    try {
      setIsLoading(true);
      const memoryData = await memoryAPI.getMemories(userId);
      setMemories(memoryData);
    } catch (error) {
      console.error('Failed to load memories:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteMemory = async (memoryId: number) => {
    try {
      setDeletingMemoryId(memoryId);
      await memoryAPI.deleteMemory(memoryId);
      setMemories(prev => prev.filter(memory => memory.id !== memoryId));
      setShowDeleteConfirm(null);
    } catch (error) {
      console.error('Failed to delete memory:', error);
    } finally {
      setDeletingMemoryId(null);
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getImportanceColor = (importance: number) => {
    if (importance >= 0.8) return 'text-red-400';
    if (importance >= 0.6) return 'text-yellow-400';
    if (importance >= 0.4) return 'text-blue-400';
    return 'text-cosmic-400';
  };

  const getImportanceLabel = (importance: number) => {
    if (importance >= 0.8) return 'Critical';
    if (importance >= 0.6) return 'Important';
    if (importance >= 0.4) return 'Moderate';
    return 'Low';
  };

  if (isLoading) {
    return (
      <div className="cosmic-card p-8 text-center">
        <Brain className="w-12 h-12 text-antara-500 mx-auto mb-4 animate-pulse" />
        <p className="text-cosmic-300">Accessing your memory sanctum...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="cosmic-card p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center">
            <Brain className="w-6 h-6 text-antara-500 mr-3" />
            <div>
              <h2 className="text-2xl font-bold text-cosmic-100">Memory Sanctum</h2>
              <p className="text-cosmic-400">Your sacred memories, under your complete control</p>
            </div>
          </div>
          <Shield className="w-8 h-8 text-antara-500/50" />
        </div>
        
        {memories.length > 0 && (
          <div className="flex items-center space-x-4 text-sm">
            <div className="text-cosmic-300">
              <span className="text-antara-400 font-semibold">{memories.length}</span> memories stored
            </div>
            <div className="text-cosmic-400">
              • Complete privacy control • Permanent deletion available
            </div>
          </div>
        )}
      </div>

      {/* Privacy Notice */}
      <div className="cosmic-card p-4 border-l-4 border-antara-500">
        <div className="flex items-start">
          <Shield className="w-5 h-5 text-antara-500 mr-3 mt-0.5 flex-shrink-0" />
          <div className="text-sm">
            <p className="text-cosmic-200 font-medium mb-1">Your Privacy, Your Control</p>
            <p className="text-cosmic-400">
              These are the memories your AI companion holds about you. You have complete control - 
              review them anytime and permanently delete any you choose. Deleted memories cannot be recovered.
            </p>
          </div>
        </div>
      </div>

      {/* Memories List */}
      {memories.length === 0 ? (
        <div className="cosmic-card p-12 text-center">
          <Brain className="w-16 h-16 text-cosmic-600 mx-auto mb-4" />
          <h3 className="text-xl font-semibold text-cosmic-300 mb-2">No memories yet</h3>
          <p className="text-cosmic-400 max-w-md mx-auto">
            As you interact with the Dream Weaver, meaningful moments will be remembered here. 
            You'll always have full control over what is kept and what is forgotten.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {memories.map((memory) => (
            <div key={memory.id} className="cosmic-card p-6 hover:bg-cosmic-700/30 transition-colors duration-200">
              <div className="flex items-start justify-between">
                <div className="flex-1 mr-4">
                  <div className="flex items-center mb-2">
                    <div className="flex items-center space-x-3">
                      <span className={`text-xs font-medium px-2 py-1 rounded-full bg-cosmic-800 ${getImportanceColor(memory.importance)}`}>
                        {getImportanceLabel(memory.importance)}
                      </span>
                      <div className="flex items-center text-cosmic-400 text-xs">
                        <Calendar className="w-3 h-3 mr-1" />
                        {formatDate(memory.timestamp)}
                      </div>
                    </div>
                  </div>
                  
                  <p className="text-cosmic-200 leading-relaxed">{memory.text}</p>
                </div>
                
                <div className="flex-shrink-0">
                  {showDeleteConfirm === memory.id ? (
                    <div className="flex items-center space-x-2">
                      <button
                        onClick={() => handleDeleteMemory(memory.id)}
                        disabled={deletingMemoryId === memory.id}
                        className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-xs rounded-lg transition-colors duration-200 disabled:opacity-50"
                      >
                        {deletingMemoryId === memory.id ? 'Deleting...' : 'Confirm'}
                      </button>
                      <button
                        onClick={() => setShowDeleteConfirm(null)}
                        className="px-3 py-1 bg-cosmic-700 hover:bg-cosmic-600 text-cosmic-300 text-xs rounded-lg transition-colors duration-200"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setShowDeleteConfirm(memory.id)}
                      className="p-2 text-cosmic-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all duration-200"
                      title="Delete this memory permanently"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
              
              {showDeleteConfirm === memory.id && (
                <div className="mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                  <div className="flex items-start">
                    <AlertTriangle className="w-4 h-4 text-red-400 mr-2 mt-0.5 flex-shrink-0" />
                    <div className="text-sm">
                      <p className="text-red-300 font-medium">Permanent Deletion</p>
                      <p className="text-red-200/80 text-xs mt-1">
                        This memory will be permanently deleted and cannot be recovered. Are you sure?
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Footer Info */}
      {memories.length > 0 && (
        <div className="cosmic-card p-4">
          <div className="flex items-center justify-center space-x-6 text-xs text-cosmic-400">
            <div className="flex items-center">
              <Sparkles className="w-3 h-3 mr-1" />
              <span>Memories help personalize your experience</span>
            </div>
            <div className="flex items-center">
              <Shield className="w-3 h-3 mr-1" />
              <span>You control what is remembered</span>
            </div>
            <div className="flex items-center">
              <Trash2 className="w-3 h-3 mr-1" />
              <span>Deletion is permanent</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MemorySanctum;
