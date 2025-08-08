import Chat from "@/components/chat";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-gray-100 dark:bg-gray-900 p-4">
      <div className="w-full max-w-4xl flex-1 flex flex-col">
        <header className="p-4 border-b dark:border-gray-800">
          <h1 className="text-2xl font-bold text-center text-gray-800 dark:text-gray-200">DeepSearchStack</h1>
          <p className="text-center text-gray-500 dark:text-gray-400">Your Private, Self-Hosted AI Search and Reasoning Engine</p>
        </header>
        <Chat />
      </div>
    </main>
  );
}