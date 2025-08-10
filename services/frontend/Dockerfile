# Stage 1: Build the React application
FROM node:18-alpine AS builder

WORKDIR /app

# CORRECTED: Copy both package.json AND package-lock.json
COPY services/frontend/package*.json ./

# Now 'npm ci' will find the package-lock.json and succeed
RUN npm ci

# Copy the rest of the application source code
COPY services/frontend/ .

# Build the application for production
# Assuming your build script is 'build' in package.json
RUN npm run build

# Stage 2: Serve the static files with Nginx
FROM nginx:1.25-alpine

# The build output is likely in a 'dist' or 'build' folder.
# We'll assume 'dist' based on Vite's default.
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy the custom Nginx configuration
COPY services/frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Start Nginx
CMD ["nginx", "-g", "daemon off;"]
