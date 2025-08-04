// axiosInstance.ts

import axios from 'axios';
import type { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios';

// Define API error interface
interface ApiError {
  message?: string;
  error?: string;
  details?: any;
}

// Function to get CSRF token from cookies
const getCSRFToken = (): string | null => {
  const name = 'csrftoken';
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
};

// Create axios instance
const axiosInstance: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1',
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  },
  timeout: 10000, // 10 seconds timeout
  withCredentials: true, // Required for CSRF token to be sent
});

// Create a function to handle file uploads with proper headers
export const uploadFile = async (url: string, formData: FormData) => {
  const token = localStorage.getItem('token');
  const csrfToken = getCSRFToken();
  
  return axios.post(`${axiosInstance.defaults.baseURL}${url}`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
      'X-CSRFToken': csrfToken || '',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    withCredentials: true,
  });
};

// Request interceptor
axiosInstance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('token');
    const csrfToken = getCSRFToken();

    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    
    // Add CSRF token to headers
    if (csrfToken) {
      config.headers['X-CSRFToken'] = csrfToken;
    }

    // Handle FormData requests
    if (config.data instanceof FormData) {
      config.headers['Content-Type'] = 'multipart/form-data';
    }
    
    return config;
  },
  (error: AxiosError) => {
    console.error('Request error:', error);
    return Promise.reject(error);
  }
);

// Response interceptor
axiosInstance.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiError>) => {
    // Handle network errors
    if (!error.response) {
      console.error('Network error:', error.message);
      throw new Error('Network error. Please check your internet connection.');
    }

    // Get the error message from the response
    const errorMessage = error.response.data?.error || 
                        error.response.data?.message || 
                        'An unexpected error occurred';

    // Handle specific error cases
    switch (error.response.status) {
      case 400:
        console.error('Bad request:', error.response.data);
        throw new Error(errorMessage);

      case 401:
        console.error('Authentication failed:', error.response.data);
        // Only clear storage and redirect if not already on login page
        if (!window.location.pathname.includes('/login')) {
          localStorage.clear();
          sessionStorage.clear();
          window.location.href = '/login';
        }
        throw new Error(errorMessage);

      case 403:
        console.error('Permission denied:', error.response.data);
        if (error.response.data.toString().includes('CSRF')) {
          throw new Error('CSRF token missing or invalid. Please refresh the page and try again.');
        }
        throw new Error(errorMessage);

      case 404:
        console.error('Resource not found:', error.response.data);
        throw new Error(errorMessage);

      case 422:
        console.error('Validation error:', error.response.data);
        throw new Error(errorMessage);

      case 429:
        console.error('Too many requests:', error.response.data);
        throw new Error('Too many requests. Please try again later');

      case 500:
        console.error('Server error:', error.response.data);
        throw new Error('An internal server error occurred. Please try again later');

      default:
        console.error('Unhandled error:', error.response.data);
        throw new Error(errorMessage);
    }
  }
);

export default axiosInstance;
