import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export interface ChatMessage {
  id?: number;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface WorldNode {
  id: number;
  title: string;
  summary: string;
  created_at: string;
}

export interface Memory {
  id: number;
  text: string;
  importance: number;
  timestamp: string;
}

export interface User {
  user_id: string;
  username: string;
  created_at: string;
}

// Chat API
export const chatAPI = {
  sendMessage: async (message: string, userId: string) => {
    const response = await api.post('/chat', {
      message,
      user_id: userId,
    });
    return response.data;
  },

  getChatHistory: async (userId: string, limit = 50) => {
    const response = await api.get(`/chat/${userId}/history?limit=${limit}`);
    return response.data;
  },
};

// User API
export const userAPI = {
  createUser: async (userId: string, username: string) => {
    const response = await api.post('/users', {
      user_id: userId,
      username,
    });
    return response.data;
  },

  getUser: async (userId: string) => {
    const response = await api.get(`/users/${userId}`);
    return response.data;
  },
};

// World Map API
export const worldAPI = {
  getWorldNodes: async (userId: string): Promise<WorldNode[]> => {
    const response = await api.get(`/world/${userId}`);
    return response.data;
  },
};

// Memory Sanctum API
export const memoryAPI = {
  getMemories: async (userId: string): Promise<Memory[]> => {
    const response = await api.get(`/memories/${userId}`);
    return response.data;
  },

  deleteMemory: async (memoryId: number) => {
    const response = await api.delete(`/memory/${memoryId}`);
    return response.data;
  },
};

export default api;
