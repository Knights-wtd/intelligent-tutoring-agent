import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("test setup", () => {
  it("renders into the test document", () => {
    render(<div>cleanup sentinel</div>);

    expect(screen.getByText("cleanup sentinel")).toBeInTheDocument();
  });

  it("cleans the test document after each test", () => {
    expect(screen.queryByText("cleanup sentinel")).not.toBeInTheDocument();
  });
});
