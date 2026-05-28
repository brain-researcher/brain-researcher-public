import { useState, useEffect } from 'react'

export function useLocalStorage<T>(
  key: string,
  defaultValue: T
): [T, (value: T | ((prev: T) => T)) => void] {
  // Initialize state with default value
  const [storedValue, setStoredValue] = useState<T>(defaultValue)

  // Load value from localStorage on mount
  useEffect(() => {
    try {
      const item = window.localStorage.getItem(key)
      if (item) {
        setStoredValue(JSON.parse(item))
      }
    } catch (error) {
      console.error(`Error loading localStorage key "${key}":`, error)
    }
  }, [key])

  // Update localStorage when value changes (supports functional updates like useState)
  const setValue = (value: T | ((prev: T) => T)) => {
    try {
      const newValue = typeof value === 'function' ? (value as (prev: T) => T)(storedValue) : value
      setStoredValue(newValue)
      window.localStorage.setItem(key, JSON.stringify(newValue))
    } catch (error) {
      console.error(`Error setting localStorage key "${key}":`, error)
    }
  }

  return [storedValue, setValue]
}