"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useEffect, useState } from "react";
import {
  getRepositories,
  getServerState,
  getSuggestions,
  updateServerMode,
  updateRepository,
  getSetupStatus,
} from "@/lib/api";
import type {
  Repository,
  ServerState,
  Suggestion,
  SetupStatus,
} from "@/lib/api";
import { SetupGuide } from "@/components/SetupGuide";

export default function Home() {
  const [serverState, setServerState] = useState<ServerState | null>(null);
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSuggestion, setSelectedSuggestion] =
    useState<Suggestion | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        // First check setup status
        const status = await getSetupStatus();
        setSetupStatus(status);

        // If setup is complete, load the rest of the data
        if (status.setup_complete) {
          const [state, reposData, suggestionsData] = await Promise.all([
            getServerState(),
            getRepositories(),
            getSuggestions(),
          ]);
          setServerState(state);
          setRepositories(reposData.repositories);
          setSuggestions(suggestionsData.suggestions);
        }
      } catch (error) {
        console.error("Failed to load data:", error);
      } finally {
        setLoading(false);
      }
    }

    loadData();
    // Poll for updates every 30 seconds
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleModeChange = async (
    mode: "disabled" | "dry_run",
    value: boolean
  ) => {
    try {
      const update =
        mode === "disabled" ? { is_disabled: value } : { dry_run: value };
      await updateServerMode(update);
      // Refresh state
      const newState = await getServerState();
      setServerState(newState);
    } catch (error) {
      console.error("Failed to update mode:", error);
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen p-8">
        <div className="max-w-6xl mx-auto">Loading...</div>
      </main>
    );
  }

  // If setup is not complete, show the setup guide
  if (setupStatus && !setupStatus.configured) {
    return (
      <main className="min-h-screen p-8">
        <div className="max-w-6xl mx-auto">
          <h1 className="text-4xl font-bold text-primary mb-8">
            Cursor Rules Bot Setup
          </h1>
          <SetupGuide setupStatus={setupStatus} />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-6xl mx-auto space-y-8">
        <h1 className="text-4xl font-bold text-primary">
          Cursor Rules Bot Admin
        </h1>

        {/* Server Controls */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-primary">Server Status</CardTitle>
              <CardDescription>
                Control the bot's operation mode
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="font-medium text-primary">Server Enabled</div>
                  <div className="text-sm text-muted-foreground">
                    Enable or disable all bot operations
                  </div>
                </div>
                <Switch
                  checked={!serverState?.mode.is_disabled}
                  onCheckedChange={(checked) =>
                    handleModeChange("disabled", !checked)
                  }
                  className="data-[state=checked]:bg-primary data-[state=checked]:hover:bg-primary/90"
                />
              </div>
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="font-medium text-primary">Dry Run Mode</div>
                  <div className="text-sm text-muted-foreground">
                    Process but don't make actual changes
                  </div>
                </div>
                <Switch
                  checked={serverState?.mode.dry_run ?? false}
                  onCheckedChange={(checked) =>
                    handleModeChange("dry_run", checked)
                  }
                  className="data-[state=checked]:bg-primary data-[state=checked]:hover:bg-primary/90"
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-primary">Statistics</CardTitle>
              <CardDescription>Current bot activity</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-2xl font-bold text-primary">
                    {repositories.length}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    Connected Repositories
                  </div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-primary">
                    {suggestions.length}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    Recent Suggestions
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Recent Activity */}
        <Card>
          <CardHeader>
            <CardTitle className="text-primary">Recent Suggestions</CardTitle>
            <CardDescription>
              Latest rule suggestions from the bot
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-[400px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Repository</TableHead>
                    <TableHead>PR</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Time</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {suggestions
                    .sort(
                      (a, b) =>
                        new Date(b.timestamp).getTime() -
                        new Date(a.timestamp).getTime()
                    )
                    .slice(0, 10)
                    .map((suggestion) => (
                      <TableRow
                        key={`${suggestion.id}-${suggestion.timestamp}`}
                        className="hover:bg-muted/50 transition-colors"
                      >
                        <TableCell className="font-medium">
                          <a
                            href={`https://github.com/${suggestion.repository}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:underline"
                          >
                            {suggestion.repository}
                          </a>
                        </TableCell>
                        <TableCell>
                          <a
                            href={`https://github.com/${suggestion.repository}/pull/${suggestion.pr_number}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:underline"
                          >
                            #{suggestion.pr_number}
                          </a>
                        </TableCell>
                        <TableCell>
                          <span
                            className={
                              suggestion.status === "applied"
                                ? "text-green-600"
                                : suggestion.status === "rejected"
                                ? "text-red-600"
                                : suggestion.status === "dry_run"
                                ? "text-orange-600"
                                : "text-blue-600"
                            }
                          >
                            {suggestion.status}
                          </span>
                        </TableCell>
                        <TableCell>
                          {new Date(suggestion.timestamp).toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-2">
                            {suggestion.comment_url && (
                              <Button variant="ghost" size="sm" asChild>
                                <a
                                  href={suggestion.comment_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  View
                                </a>
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setSelectedSuggestion(suggestion);
                                setDialogOpen(true);
                              }}
                            >
                              Details
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Suggestion Details Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>Suggestion Details</DialogTitle>
            <DialogDescription>
              {selectedSuggestion && (
                <span>
                  For{" "}
                  <a
                    href={`https://github.com/${selectedSuggestion.repository}/pull/${selectedSuggestion.pr_number}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium hover:underline"
                  >
                    {selectedSuggestion.repository}#
                    {selectedSuggestion.pr_number}
                  </a>
                </span>
              )}
            </DialogDescription>
          </DialogHeader>
          {selectedSuggestion && (
            <div className="space-y-4">
              <div>
                <h3 className="font-medium">File Path</h3>
                <p className="text-sm">{selectedSuggestion.file_path}</p>
              </div>
              <div>
                <h3 className="font-medium">Status</h3>
                <p
                  className={
                    selectedSuggestion.status === "applied"
                      ? "text-green-600"
                      : selectedSuggestion.status === "rejected"
                      ? "text-red-600"
                      : selectedSuggestion.status === "dry_run"
                      ? "text-orange-600"
                      : "text-blue-600"
                  }
                >
                  {selectedSuggestion.status}
                </p>
              </div>
              <div>
                <h3 className="font-medium">Suggestion</h3>
                <pre className="bg-muted p-4 rounded-md overflow-auto text-sm whitespace-pre-wrap">
                  {selectedSuggestion.suggestion_text}
                </pre>
              </div>
              {selectedSuggestion.dry_run_preview && (
                <div>
                  <h3 className="font-medium">Dry Run Preview</h3>
                  <pre className="bg-muted p-4 rounded-md overflow-auto text-sm whitespace-pre-wrap">
                    {selectedSuggestion.dry_run_preview.content}
                  </pre>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </main>
  );
}
