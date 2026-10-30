import { RouterProvider } from '@tanstack/react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { router } from './router';
import { WorkspaceProvider } from './workspace/WorkspaceContext';
import { isAccessDenied } from './lib/access';
import './styles.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A private player stays private; retrying only delays the explanation.
      retry: (failures, error) => !isAccessDenied(error) && failures < 3
    }
  }
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WorkspaceProvider>
        <RouterProvider router={router} />
      </WorkspaceProvider>
    </QueryClientProvider>
  );
}

export default App;
