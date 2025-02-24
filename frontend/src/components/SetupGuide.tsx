import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { SetupStatus } from "@/lib/api";

export function SetupGuide({ setupStatus }: { setupStatus: SetupStatus }) {
  const missingVars = Object.entries(setupStatus.variables)
    .filter(([_, isSet]) => !isSet)
    .map(([name]) => name);

  return (
    <div className="space-y-8">
      <Card className="border-amber-500">
        <CardHeader>
          <CardTitle className="text-amber-600">Setup Required</CardTitle>
          <CardDescription>
            The Cursor Rules Bot needs configuration before it can run.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <p>The following environment variables need to be set:</p>
            <ul className="list-disc pl-5 space-y-1">
              {missingVars.map((varName) => (
                <li key={varName} className="text-amber-700">
                  {varName === "LLM_API_KEY"
                    ? "ANTHROPIC_API_KEY or OPENAI_API_KEY"
                    : varName}
                </li>
              ))}
            </ul>
            <p className="text-sm text-amber-600 mt-4">
              Please set these environment variables in your Cloud Run service
              and restart it for changes to take effect.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>GitHub App Setup Guide</CardTitle>
          <CardDescription>
            Follow these steps to create and configure your GitHub App
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ol className="list-decimal pl-5 space-y-4">
            <li>
              <strong>Create a GitHub App</strong>
              <p className="text-sm text-muted-foreground mt-1">
                Go to your GitHub profile settings → Developer settings → GitHub
                Apps → New GitHub App
              </p>
              <ul className="list-disc pl-5 mt-2 text-sm">
                <li>
                  <strong>Name</strong>: Cursor Rules Bot (or your preferred
                  name)
                </li>
                <li>
                  <strong>Homepage URL</strong>: Your Cloud Run URL
                </li>
                <li>
                  <strong>Webhook URL</strong>: Your Cloud Run URL + /webhook
                </li>
                <li>
                  <strong>Webhook Secret</strong>: Generate a random string
                </li>
              </ul>
            </li>
            <li>
              <strong>Set Permissions</strong>
              <ul className="list-disc pl-5 mt-2 text-sm">
                <li>Repository contents: Read & write</li>
                <li>Pull requests: Read & write</li>
                <li>Issues: Read & write</li>
                <li>
                  Subscribe to events: Issue comment, Pull request review
                  comment
                </li>
              </ul>
            </li>
            <li>
              <strong>Generate a Private Key</strong>
              <p className="text-sm text-muted-foreground mt-1">
                After creating the app, scroll down and click "Generate a
                private key"
              </p>
            </li>
            <li>
              <strong>Install the App</strong>
              <p className="text-sm text-muted-foreground mt-1">
                Click "Install App" in the sidebar and choose repositories
              </p>
            </li>
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}
