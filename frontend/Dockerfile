# Dev-only image for local UI testing (avoids failing `tsc && vite build` during early development).
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .

EXPOSE 3000

# Vite reads `VITE_*` env vars at runtime in dev
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
