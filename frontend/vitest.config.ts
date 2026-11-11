import { availableParallelism } from 'node:os'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    clearMocks: true,
    // Running every jsdom workspace at once can starve integration tests of CPU time.
    maxWorkers: Math.min(6, Math.max(1, availableParallelism() - 1)),
  },
})
