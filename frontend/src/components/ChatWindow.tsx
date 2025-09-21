import React, { useState, useEffect, useRef } from 'react';
import { Send, Sparkles, User } from 'lucide-react';
import { chatAPI, ChatMessage } from '../services/api';

interface ChatWindowProps {
  userId: string;
}

const ChatWindow: React.FC<ChatWindowProps> = ({ userId }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadChatHistory();
  }, [userId]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const loadChatHistory = async () => {
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
    setInputMessage('');
    setIsLoading(true);

    try {
      const response = await chatAPI.sendMessage(inputMessage, userId);
      
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
      
    } catch (error) {
      console.error('Failed to send message:', error);
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: 'The mystical connection wavers... Please try again in a moment.',
        timestamp: new Date().toISOString(),
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="cosmic-card h-[600px] chat-container">
      {/* Chat Header */}
      <div className="p-6 border-b border-cosmic-700/50 flex-shrink-0">
        <div className="flex items-center">
          <Sparkles className="w-6 h-6 text-antara-500 mr-3 animate-pulse" />
          <div>
            <h2 className="text-xl font-semibold text-cosmic-100">Dream Weaver</h2>
            <p className="text-cosmic-400 text-sm">Your mystical guide to inner landscapes</p>
          </div>
        </div>
      </div>

      {/* Messages Container */}
      <div
        ref={chatContainerRef}
        className="messages-area p-6 space-y-6"
        style={{ scrollBehavior: 'smooth' }}
      >
        {messages.length === 0 && (
          <div className="text-center text-cosmic-400 mt-12">
            <Sparkles className="w-12 h-12 mx-auto mb-4 text-antara-500/50" />
            <p className="text-lg mb-2">Welcome to your inner world</p>
            <p className="text-sm">Share a thought or feeling, and watch as new elements appear in your mystical landscape...</p>
          </div>
        )}
        
        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div className={`flex max-w-[90%] w-full ${message.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
              {/* Avatar */}
              <div className={`flex-shrink-0 ${message.role === 'user' ? 'ml-3' : 'mr-3'}`}>
                <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                  message.role === 'user' 
                    ? 'bg-antara-500/20 text-antara-400' 
                    : 'bg-cosmic-700/50 text-cosmic-300'
                }`}>
                  {message.role === 'user' ? (
                    <User className="w-4 h-4" />
                  ) : (
                    <Sparkles className="w-4 h-4" />
                  )}
                </div>
              </div>
              
              {/* Message Content */}
              <div className={`px-4 py-3 rounded-2xl flex-1 min-w-0 ${
                message.role === 'user'
                  ? 'bg-antara-500/20 text-antara-100'
                  : 'bg-cosmic-700/30 text-cosmic-200'
              }`}>
                <p className={`dream-text break-words whitespace-pre-wrap overflow-hidden ${isTyping && index === messages.length - 1 ? 'typewriter-effect' : ''}`}>
                  {message.content}
                </p>
              </div>
            </div>
          </div>
        ))}
        
        {isLoading && (
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
        
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="p-6 border-t border-cosmic-700/50 flex-shrink-0">
        <div className="flex space-x-4">
          <textarea
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Share what's in your heart..."
            className="flex-1 bg-cosmic-800/50 border border-cosmic-600/50 rounded-xl px-4 py-3 text-cosmic-100 placeholder-cosmic-400 focus:outline-none focus:ring-2 focus:ring-antara-500/50 focus:border-antara-500/50 resize-none min-h-[80px] max-h-[120px]"
            rows={2}
            disabled={isLoading}
          />
          <button
            onClick={handleSendMessage}
            disabled={!inputMessage.trim() || isLoading}
            className="px-6 py-3 bg-antara-500 hover:bg-antara-600 disabled:bg-cosmic-700 disabled:text-cosmic-500 text-white rounded-xl transition-colors duration-200 flex items-center justify-center self-end"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatWindow;
