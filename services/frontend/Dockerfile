# Dockerfile for the Next.js frontend

# 1. Build stage
FROM node:18-alpine AS builder
WORKDIR /app

# Copy package.json and package-lock.json
COPY services/frontend/package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application code
COPY services/frontend/ .

# Build the Next.js application
RUN npm run build

# 2. Production stage
FROM node:18-alpine
WORKDIR /app

# Copy the built application from the builder stage
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/public ./public

# Expose the port the app runs on
EXPOSE 3000

# Start the Next.js application
CMD ["npm", "start"]
