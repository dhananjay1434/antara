import React, { useState, useEffect, useRef } from 'react';
import { Send, Sparkles, User } from 'lucide-react';
import { chatAPI, actionAPI, ChatMessage } from '../services/api';

interface ChatWindowProps {
  userId: string;
}

const ChatWindow: React.FC<ChatWindowProps> = ({ userId }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [isSynthesizing, setIsSynthesizing] = useState(false);
  const [synthesisStep, setSynthesisStep] = useState(0);
  const [currentNodeId, setCurrentNodeId] = useState<number | null>(null);
  const [actionInput, setActionInput] = useState('');
  const [isActionSubmitted, setIsActionSubmitted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (userId) {
      loadChatHistory();
    }
  }, [userId]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const loadChatHistory = async () => {
    if (!userId) return;

    try {
      const history = await chatAPI.getChatHistory(userId);
      setMessages(history);
    } catch (error) {
      console.error('Failed to load chat history:', error);
    }
  };

  const scrollToBottom = () => {
    if (messagesEndRef.current && chatContainerRef.current) {
      // Use both methods to ensure scrolling works
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
      // Also scroll the container to bottom
      setTimeout(() => {
        if (chatContainerRef.current) {
          chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
        }
      }, 100);
    }
  };

  const handleMagicMoment = (nodeId: number) => {
    setCurrentNodeId(nodeId);
    setIsActionSubmitted(false); // Reset in case of another magic moment
  };

  const handleActionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentNodeId || !actionInput.trim()) return;

    try {
      await actionAPI.saveActionForNode(currentNodeId, actionInput);
      setIsActionSubmitted(true); // Show confirmation
      setTimeout(() => {
        setCurrentNodeId(null); // Hide the prompt after a delay
      }, 2000);
      setActionInput('');
    } catch (error) {
      console.error("Failed to submit action:", error);
      // You could add some user-facing error state here
    }
  };

  const typewriterEffect = (text: string, callback: (displayText: string) => void) => {
    let i = 0;
    const speed = 30; // Typing speed in milliseconds
    
    const typeWriter = () => {
      if (i < text.length) {
        callback(text.substring(0, i + 1));
        i++;
        setTimeout(typeWriter, speed);
      } else {
        setIsTyping(false);
      }
    };
    
    typeWriter();
  };

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      role: 'user',
      content: inputMessage,
      timestamp: new Date().toISOString(),
    };

    setMessages(prev => [...prev, userMessage]);
    const currentInput = inputMessage;
    setInputMessage('');
    setIsLoading(true);

    // Check if this is a Crystal Labyrinth trigger
    const crystalTriggers = [
      'everyone else is better than me',
      'everyone else has it all figured out',
      'i feel like everyone else',
      'everyone is better than me',
      'others are better than me'
    ];

    const isCrystalTrigger = crystalTriggers.some(trigger =>
      currentInput.toLowerCase().includes(trigger)
    );

    try {
      if (isCrystalTrigger) {
        // Start synthesis visualization
        setIsSynthesizing(true);
        setSynthesisStep(0);

        // Animate synthesis steps with longer timing for better appreciation
        setTimeout(() => setSynthesisStep(1), 800);   // Increased from 300ms
        setTimeout(() => setSynthesisStep(2), 1600);  // Increased from 600ms
        setTimeout(() => setSynthesisStep(3), 2400);  // Increased from 900ms
        setTimeout(() => setSynthesisStep(4), 3200);  // Increased from 1200ms

        // Wait 5 seconds then fade out and start response (increased from 2 seconds)
        setTimeout(async () => {
          setIsSynthesizing(false);
          setSynthesisStep(0);

          // Get the actual response
          const response = await chatAPI.sendMessage(currentInput, userId);

          // Check for Magic Moment node_id
          if (response.node_id) {
            handleMagicMoment(response.node_id);
          }

          // Add AI message with typewriter effect
          const aiMessage: ChatMessage = {
            role: 'assistant',
            content: '',
            timestamp: new Date().toISOString(),
          };

          setMessages(prev => [...prev, aiMessage]);
          setIsTyping(true);

          // Simulate typewriter effect
          typewriterEffect(response.response, (displayText) => {
            setMessages(prev =>
              prev.map((msg, index) =>
                index === prev.length - 1
                  ? { ...msg, content: displayText }
                  : msg
              )
            );
          });
          setIsLoading(false);
        }, 5000); // Increased from 2000ms to allow full appreciation of synthesis

      } else {
        // Normal message flow
        const response = await chatAPI.sendMessage(currentInput, userId);

        // Check for Magic Moment node_id (in case of non-synthesis triggers)
        if (response.node_id) {
          handleMagicMoment(response.node_id);
        }

        // Add AI message with typewriter effect
        const aiMessage: ChatMessage = {
          role: 'assistant',
          content: '',
          timestamp: new Date().toISOString(),
        };

        setMessages(prev => [...prev, aiMessage]);
        setIsTyping(true);

        // Simulate typewriter effect
        typewriterEffect(response.response, (displayText) => {
          setMessages(prev =>
            prev.map((msg, index) =>
              index === prev.length - 1
                ? { ...msg, content: displayText }
                : msg
            )
          );
        });
        setIsLoading(false);
      }

    } catch (error) {
      console.error('Failed to send message:', error);
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: 'The mystical connection wavers... Please try again in a moment.',
        timestamp: new Date().toISOString(),
      };
      setMessages(prev => [...prev, errorMessage]);
      setIsLoading(false);
      setIsSynthesizing(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="cosmic-card h-[600px] sm:h-[700px] chat-container overflow-hidden">
      {/* Chat Header */}
      <div className="p-4 sm:p-6 border-b border-cosmic-700/50 flex-shrink-0">
        <div className="flex items-center">
          <Sparkles className="w-5 h-5 sm:w-6 sm:h-6 text-antara-500 mr-2 sm:mr-3 animate-pulse" />
          <div>
            <h2 className="text-lg sm:text-xl font-semibold text-cosmic-100">Dream Weaver</h2>
            <p className="text-cosmic-400 text-xs sm:text-sm">Your mystical guide to inner landscapes</p>
          </div>
        </div>
      </div>

      {/* Messages Container */}
      <div
        ref={chatContainerRef}
        className="messages-area p-3 sm:p-6 space-y-4 sm:space-y-6 overflow-y-auto"
        style={{ scrollBehavior: 'smooth' }}
      >
        {messages.length === 0 && (
          <div className="text-center text-cosmic-400 mt-8 sm:mt-12 px-4">
            <Sparkles className="w-10 h-10 sm:w-12 sm:h-12 mx-auto mb-3 sm:mb-4 text-antara-500/50" />
            <p className="text-base sm:text-lg mb-2">Welcome to your inner world</p>
            <p className="text-xs sm:text-sm">Share a thought or feeling, and watch as new elements appear in your mystical landscape...</p>
          </div>
        )}
        
        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div className={`flex max-w-[95%] sm:max-w-[90%] w-full ${message.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
              {/* Avatar */}
              <div className={`flex-shrink-0 ${message.role === 'user' ? 'ml-2 sm:ml-3' : 'mr-2 sm:mr-3'}`}>
                <div className={`w-6 h-6 sm:w-8 sm:h-8 rounded-full flex items-center justify-center ${
                  message.role === 'user'
                    ? 'bg-antara-500/20 text-antara-400'
                    : 'bg-cosmic-700/50 text-cosmic-300'
                }`}>
                  {message.role === 'user' ? (
                    <User className="w-3 h-3 sm:w-4 sm:h-4" />
                  ) : (
                    <Sparkles className="w-3 h-3 sm:w-4 sm:h-4" />
                  )}
                </div>
              </div>

              {/* Message Content */}
              <div className={`px-3 sm:px-4 py-2 sm:py-3 rounded-2xl flex-1 min-w-0 ${
                message.role === 'user'
                  ? 'bg-antara-500/20 text-antara-100'
                  : 'bg-cosmic-700/30 text-cosmic-200'
              }`}>
                <p className={`dream-text break-words whitespace-pre-wrap overflow-hidden text-sm sm:text-base ${isTyping && index === messages.length - 1 ? 'typewriter-effect' : ''}`}>
                  {message.content}
                </p>
              </div>
            </div>
          </div>
        ))}
        
        {isLoading && !isSynthesizing && (
          <div className="flex justify-start">
            <div className="flex mr-3">
              <div className="w-8 h-8 rounded-full bg-cosmic-700/50 text-cosmic-300 flex items-center justify-center">
                <Sparkles className="w-4 h-4 animate-spin" />
              </div>
            </div>
            <div className="px-4 py-3 rounded-2xl bg-cosmic-700/30 text-cosmic-200">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-antara-500 rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-antara-500 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                <div className="w-2 h-2 bg-antara-500 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
              </div>
            </div>
          </div>
        )}

        {/* Synthesis Visualization */}
        {isSynthesizing && (
          <div className="flex justify-start">
            <div className="flex mr-2 sm:mr-3">
              <div className="w-6 h-6 sm:w-8 sm:h-8 rounded-full bg-gradient-to-r from-antara-500 to-purple-500 text-white flex items-center justify-center">
                <Sparkles className="w-3 h-3 sm:w-4 sm:h-4 animate-pulse" />
              </div>
            </div>
            <div className="px-4 sm:px-6 py-4 sm:py-5 rounded-2xl bg-gradient-to-r from-cosmic-700/50 to-purple-900/50 border border-antara-500/40 min-w-[280px] sm:min-w-[350px] max-w-[90%] shadow-xl shadow-antara-500/10">
              <div className="text-antara-200 text-sm sm:text-base font-semibold mb-3 sm:mb-4 flex items-center">
                <div className="w-2 h-2 sm:w-3 sm:h-3 bg-antara-400 rounded-full animate-pulse mr-2 sm:mr-3 shadow-lg shadow-antara-500/50"></div>
                Synthesizing Core Emotions...
              </div>
              <div className="flex flex-wrap gap-2 sm:gap-3">
                <div className={`px-2 sm:px-4 py-1 sm:py-2 rounded-full text-xs sm:text-sm font-semibold transition-all duration-500 ${
                  synthesisStep >= 1
                    ? 'bg-red-500/30 text-red-200 border border-red-400/50 opacity-100 scale-100 shadow-lg shadow-red-500/20'
                    : 'opacity-0 scale-75'
                }`}>
                  [Comparison]
                </div>
                <div className={`px-2 sm:px-4 py-1 sm:py-2 rounded-full text-xs sm:text-sm font-semibold transition-all duration-500 ${
                  synthesisStep >= 2
                    ? 'bg-blue-500/30 text-blue-200 border border-blue-400/50 opacity-100 scale-100 shadow-lg shadow-blue-500/20'
                    : 'opacity-0 scale-75'
                }`}>
                  [Isolation]
                </div>
                <div className={`px-2 sm:px-4 py-1 sm:py-2 rounded-full text-xs sm:text-sm font-semibold transition-all duration-500 ${
                  synthesisStep >= 3
                    ? 'bg-orange-500/30 text-orange-200 border border-orange-400/50 opacity-100 scale-100 shadow-lg shadow-orange-500/20'
                    : 'opacity-0 scale-75'
                }`}>
                  [Perceived Failure]
                </div>
                <div className={`px-2 sm:px-4 py-1 sm:py-2 rounded-full text-xs sm:text-sm font-semibold transition-all duration-500 ${
                  synthesisStep >= 4
                    ? 'bg-purple-500/30 text-purple-200 border border-purple-400/50 opacity-100 scale-100 shadow-lg shadow-purple-500/20'
                    : 'opacity-0 scale-75'
                }`}>
                  [Pressure]
                </div>
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* Action Prompt - From Metaphor to Mastery */}
      {currentNodeId && (
        <div className="mx-3 sm:mx-6 mb-3 sm:mb-4 p-4 sm:p-6 border border-antara-500/50 rounded-xl bg-gradient-to-r from-antara-900/20 to-purple-900/20 backdrop-blur-sm transition-all duration-500">
          {!isActionSubmitted ? (
            <form onSubmit={handleActionSubmit}>
              <div className="flex items-start mb-3">
                <Sparkles className="w-4 h-4 sm:w-5 sm:h-5 text-antara-400 mr-2 animate-pulse flex-shrink-0 mt-0.5" />
                <p className="text-antara-300 font-medium text-sm sm:text-base">
                  We've mapped this labyrinth. What is one small stone you can turn over tomorrow to find a new path?
                </p>
              </div>
              <input
                type="text"
                value={actionInput}
                onChange={(e) => setActionInput(e.target.value)}
                className="w-full bg-cosmic-800/50 border border-cosmic-600/50 rounded-lg px-3 sm:px-4 py-2 sm:py-3 text-cosmic-100 placeholder-cosmic-400 focus:outline-none focus:ring-2 focus:ring-antara-500/50 focus:border-antara-500/50 mb-3 text-sm sm:text-base"
                placeholder="e.g., Talk to one friend about my project..."
                autoFocus
              />
              <button
                type="submit"
                disabled={!actionInput.trim()}
                className="w-full bg-antara-500 hover:bg-antara-600 disabled:bg-cosmic-700 disabled:text-cosmic-500 text-white font-semibold py-2 sm:py-3 px-4 rounded-lg transition-colors duration-200 text-sm sm:text-base"
              >
                Anchor This Intention
              </button>
            </form>
          ) : (
            <div className="text-center">
              <Sparkles className="w-6 h-6 sm:w-8 sm:h-8 text-green-400 mx-auto mb-2 sm:mb-3 animate-pulse" />
              <p className="text-green-400 font-medium text-sm sm:text-base">Your intention has been anchored to this memory.</p>
              <p className="text-cosmic-400 text-xs sm:text-sm mt-1 sm:mt-2">The labyrinth remembers your commitment.</p>
            </div>
          )}
        </div>
      )}

      {/* Input Area */}
      <div className="p-3 sm:p-6 border-t border-cosmic-700/50 flex-shrink-0">
        <div className="flex space-x-2 sm:space-x-4">
          <textarea
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Share what's in your heart..."
            className="flex-1 bg-cosmic-800/50 border border-cosmic-600/50 rounded-xl px-3 sm:px-4 py-2 sm:py-3 text-cosmic-100 placeholder-cosmic-400 focus:outline-none focus:ring-2 focus:ring-antara-500/50 focus:border-antara-500/50 resize-none min-h-[60px] sm:min-h-[80px] max-h-[100px] sm:max-h-[120px] text-sm sm:text-base"
            rows={2}
            disabled={isLoading}
          />
          <button
            onClick={handleSendMessage}
            disabled={!inputMessage.trim() || isLoading}
            className="px-3 sm:px-6 py-2 sm:py-3 bg-antara-500 hover:bg-antara-600 disabled:bg-cosmic-700 disabled:text-cosmic-500 text-white rounded-xl transition-colors duration-200 flex items-center justify-center self-end"
          >
            <Send className="w-4 h-4 sm:w-5 sm:h-5" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatWindow;
