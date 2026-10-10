import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{host:'127.0.0.1',strictPort:true,cors:{origin:process.env.FAULTLINE_FRONTEND||'http://127.0.0.1:5173'},proxy:{'/api':process.env.FAULTLINE_API_URL||'http://127.0.0.1:8000'}},build:{rollupOptions:{output:{manualChunks(id){if(/node_modules\/(react|react-dom|scheduler)\//.test(id))return 'react';if(id.includes('node_modules/'))return 'vendor'}}}}});
