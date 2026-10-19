"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { readStoredEstimate, storeEstimate, storePrefillEmail } from "@/lib/session";
import { markStepComplete } from "@/lib/journey";
import { Spinner } from "./ui";

const TOUR_STORAGE_KEY = "the-estimator:tour-completed";

// Professional SVG Icons (zero emojis)
function IconCompass({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
    </svg>
  );
}

function IconCheck({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function IconArrowRight({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="5" y1="12" x2="19" y2="12" />
      <polyline points="12 5 19 12 12 19" />
    </svg>
  );
}

function IconArrowLeft({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  );
}

function IconClose({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function IconZap({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  );
}

function IconInfo({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  );
}

function IconSparkles({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
    </svg>
  );
}

function IconMousePointer({ className = "w-3.5 h-3.5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m3 3 7.07 16.97 2.51-7.39 7.39-2.51L3 3z" />
      <path d="m13 13 6 6" />
    </svg>
  );
}

export interface TourStep {
  id: string;
  route: string;
  selector: string;
  category: string;
  title: string;
  purpose: string;
  guidance: string;
  ahaMoment: string;
  actionButton?: {
    label: string;
    actionId: "load_fintech" | "select_demo_b" | "answer_question" | "run_replay";
  };
}

// 8-step guided journey constant (defined outside component so reference never changes)
export const STEPS: TourStep[] = [
  {
    id: "sample_scenarios",
    route: "/",
    selector: '[data-tour="onboarding-samples"]',
    category: "BƯỚC 1/8 · ONBOARDING",
    title: "Tải kịch bản mẫu RFP (1-Click Presets)",
    purpose:
      "Chỗ này làm gì: Tích hợp sẵn 3 RFP thực tế (Fintech SaaS, Healthtech MVP, E-commerce). Thay vì tự soạn prompt hay dán email dài, chỉ cần 1 click là nạp toàn bộ dữ liệu vào pipeline.",
    guidance:
      "Hướng dẫn thao tác: Click vào kịch bản “Fintech payment + PCI” (hoặc bấm nút thực thi bên dưới) để tự nạp dữ liệu và chuyển sang màn hình dự toán.",
    ahaMoment:
      "Toàn bộ 15 tính năng, bằng chứng câu trích dẫn và khoảng nỗ lực P10/P50/P90 được xử lý ngay lập tức.",
    actionButton: {
      label: "Nạp Scenario Fintech & Chuyển sang Estimate",
      actionId: "load_fintech",
    },
  },
  {
    id: "import_csv",
    route: "/",
    selector: '[data-tour="onboarding-import"]',
    category: "BƯỚC 2/8 · CALIBRATION",
    title: "Huấn luyện mô hình từ lịch sử (Import CSV)",
    purpose:
      "Chỗ này làm gì: Cho phép nhập 50–60 dự án đã bàn giao từ Jira hoặc Harvest. Thuật toán Ridge Regression sẽ tự hiệu chỉnh hệ số nỗ lực theo năng suất thực tế của team bạn, thay vì áp đặt chuẩn ngành mặc định.",
    guidance:
      "Hướng dẫn thao tác: Bấm nút “Import CSV…” để tải lên file dữ liệu lịch sử. Các dòng dữ liệu lỗi sẽ được cảnh báo chi tiết thay vì âm thầm bị bỏ qua.",
    ahaMoment:
      "Mỗi dự án hoàn thành nạp vào hệ thống trở thành mẫu học mới, giúp khoảng dự toán ngày càng sắc bén.",
  },
  {
    id: "estimate_input",
    route: "/estimate",
    selector: '[data-tour="estimate-email-box"]',
    category: "BƯỚC 3/8 · EXTRACTION",
    title: "Hộp nhập RFP & Extractor chỉ đọc hiểu",
    purpose:
      "Chỗ này làm gì: Dán toàn bộ email khách hàng (tiếng Anh hoặc tiếng Việt). Extractor LLM chỉ làm nhiệm vụ “đọc hiểu” để trích xuất 15 thuộc tính kỹ thuật kèm câu chữ bằng chứng cụ thể — tuyệt đối không bịa số dự toán.",
    guidance:
      "Hướng dẫn thao tác: Có thể chỉnh sửa nội dung RFP trực tiếp tại đây. Nhấn tổ hợp phím Ctrl+Enter để chạy lại pipeline ước lượng.",
    ahaMoment:
      "Các con số P10/P50/P90 sinh ra 100% từ mô hình toán thống kê có thể kiểm toán, không phải hallucination từ LLM.",
  },
  {
    id: "codebase_context",
    route: "/estimate",
    selector: '[data-tour="codebase-selector"]',
    category: "BƯỚC 4/8 · CODEBASE LAB",
    title: "Đo hệ số ma sát kỹ thuật (Codebase Friction)",
    purpose:
      "Chỗ này làm gì: Dự án làm trên codebase sạch (Plugin pattern) sẽ nhanh hơn so với codebase lộn xộn (Spaghetti). Hệ thống phân tích AST, độ phức tạp Cyclomatic và commit churn từ Git để nhân hệ số rủi ro vào dự toán.",
    guidance:
      "Hướng dẫn thao tác: Chọn thử giữa “Demo A (plugin)” và “Demo B (spaghetti)” rồi bấm Estimate để quan sát khoảng thời gian thay đổi.",
    ahaMoment:
      "Rủi ro kỹ thuật từ nợ công nghệ (tech debt) được lượng hóa bằng toán học rõ ràng, không đoán mò.",
    actionButton: {
      label: "Thử chọn Demo B (Spaghetti - Tăng ma sát)",
      actionId: "select_demo_b",
    },
  },
  {
    id: "estimate_chart",
    route: "/estimate",
    selector: '[data-tour="estimate-chart-section"]',
    category: "BƯỚC 5/8 · RANGE ESTIMATE",
    title: "Khoảng nỗ lực thống kê [P10, P50, P90]",
    purpose:
      "Chỗ này làm gì: Cam kết một con số cố định với khách hàng là nguyên nhân hàng đầu gây vỡ tiến độ. Hệ thống trả về khoảng tin cậy 80% (Conformal Prediction): P10 (thuận lợi), P50 (khả thi nhất), P90 (an toàn bao quát biến số).",
    guidance:
      "Hướng dẫn thao tác: Quan sát bề rộng của dải nỗ lực. Dự án càng nhiều điểm mơ hồ thì khoảng càng rộng; khi đã rõ ràng thì dải sẽ co hẹp lại.",
    ahaMoment:
      "Báo giá bằng khoảng tin cậy chuẩn thống kê là cách bảo vệ tốt nhất cho ngân sách và uy tín của studio phát triển phần mềm.",
  },
  {
    id: "ranked_questions",
    route: "/estimate",
    selector: '[data-tour="questions-section"]',
    category: "BƯỚC 6/8 · VALUE OF INFORMATION",
    title: "Câu hỏi xếp hạng VOI (Giảm phương sai)",
    purpose:
      "Chỗ này làm gì: Tự động xếp hạng các câu hỏi kỹ thuật cần hỏi khách hàng theo Giá trị thông tin (VOI). Trả lời các câu hỏi này sẽ giải quyết điểm mù và làm giảm phương sai dự toán ngay lập tức.",
    guidance:
      "Hướng dẫn thao tác: Bấm nút “Có” hoặc “Không” ở từng câu hỏi để xem dải P10-P90 co ngót (shrink variance) ngay trước mắt bạn.",
    ahaMoment:
      "Giúp PM biết chính xác nên hỏi khách hàng câu gì trước trong buổi họp để giảm thiểu tối đa rủi ro dự án.",
    actionButton: {
      label: "Thử trả lời câu hỏi mẫu để xem độ co ngót",
      actionId: "answer_question",
    },
  },
  {
    id: "package_builder",
    route: "/estimate",
    selector: '[data-tour="package-builder-section"]',
    category: "BƯỚC 7/8 · SCOPE PACKAGES",
    title: "Đóng gói Scope chào thầu (Pessimistic / Balanced / Agile)",
    purpose:
      "Chỗ này làm gì: Tự động phân chia tính năng thành 3 gói chào hàng cho khách: Gói MVP tối thiểu (ra mắt nhanh), Gói Cân bằng chuẩn, và Gói Đầy đủ tính năng kèm theo chi phí và cam kết ngày bàn giao.",
    guidance:
      "Hướng dẫn thao tác: Có thể tùy chỉnh bật/tắt các tính năng trong từng gói và bấm “Print proposal” ở trên để in bản đề xuất chào thầu chuyên nghiệp.",
    ahaMoment:
      "Khách hàng luôn cảm thấy an tâm và hài lòng hơn khi nhận được bản chào thầu có nhiều lựa chọn rõ ràng về phạm vi và ngân sách.",
  },
  {
    id: "proof_replay",
    route: "/proof",
    selector: '[data-tour="proof-replay-panel"]',
    category: "BƯỚC 8/8 · PROOF & CALIBRATION",
    title: "Kiểm chứng Walk-Forward Replay & Brier Score",
    purpose:
      "Chỗ này làm gì: Khác biệt then chốt giữa The Estimator và các AI wrapper thông thường: Tính năng Walk-Forward Replay chạy kiểm thử mô hình trên từng dự án lịch sử để chứng minh độ phủ thực tế đạt 75-85% chuẩn thống kê.",
    guidance:
      "Hướng dẫn thao tác: Bấm “Run Replay” để xem mô hình chạy kiểm thử cuộn qua toàn bộ lịch sử và đo lường sai số MAE.",
    ahaMoment:
      "Mọi con số ước lượng đều có cơ sở khoa học chứng minh, minh bạch và giải trình được với các bên liên quan.",
    actionButton: {
      label: "Chạy Replay kiểm chứng ngay",
      actionId: "run_replay",
    },
  },
];

export function SpotlightTour() {
  const router = useRouter();
  const pathname = usePathname();

  const [isActive, setIsActive] = useState(false);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);

  // Viewport rect for SVG mask hole
  const [targetViewportRect, setTargetViewportRect] = useState<DOMRect | null>(null);

  // Document coordinates (absolute) for highlight ring and card
  const [targetDocCoords, setTargetDocCoords] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
  } | null>(null);

  const [cardCoords, setCardCoords] = useState<{ left: number; top: number }>({ left: 16, top: 16 });
  const [isExecutingAction, setIsExecutingAction] = useState(false);
  const [isPreparingEstimate, setIsPreparingEstimate] = useState(false);

  const cardRef = useRef<HTMLDivElement | null>(null);

  // Guard: track which step has already been scrolled to.
  // NEVER scroll more than once per step!
  const hasScrolledStepRef = useRef<number | null>(null);

  const currentStep = STEPS[currentStepIndex] || STEPS[0];

  // Auto Pop-up on First Visit (checked via localStorage)
  useEffect(() => {
    try {
      const hasCompleted = localStorage.getItem(TOUR_STORAGE_KEY);
      if (!hasCompleted) {
        const timer = setTimeout(() => {
          setIsActive(true);
          setCurrentStepIndex(0);
        }, 400);
        return () => clearTimeout(timer);
      }
    } catch {
      // Storage access fallback
    }
  }, []);

  // Compute Popover Position in Document Coordinates with Stable Placement (no jumping)
  const positionCardAndHighlight = useCallback(() => {
    if (!isActive) return;

    if (currentStep.route !== pathname) {
      setTargetViewportRect(null);
      setTargetDocCoords(null);
      return;
    }

    const el = document.querySelector<HTMLElement>(currentStep.selector);
    if (!el) {
      setTargetViewportRect(null);
      setTargetDocCoords(null);
      return;
    }

    // 1. Viewport coordinates (for SVG mask cutout)
    const vRect = el.getBoundingClientRect();
    setTargetViewportRect(vRect);

    // 2. Document coordinates (for absolute highlight ring)
    const scrollY = window.pageYOffset || document.documentElement.scrollTop;
    const scrollX = window.pageXOffset || document.documentElement.scrollLeft;

    const docTop = vRect.top + scrollY;
    const docLeft = vRect.left + scrollX;

    setTargetDocCoords({
      left: docLeft,
      top: docTop,
      width: vRect.width,
      height: vRect.height,
    });

    // 3. Stable Document-Relative Placement for Card (invariant to scroll position)
    const cardWidth = 420;
    const cardEl = cardRef.current;
    const cardHeight = cardEl ? cardEl.offsetHeight : 340;
    const gap = 16;
    const docWidth = document.documentElement.clientWidth;

    let computedDocLeft = docLeft;
    let computedDocTop = docTop + vRect.height + gap;

    // If element is tall (> 260px) and there is ample horizontal space (e.g. desktop >= 1200px)
    if (vRect.height > 260 && docWidth >= 1200) {
      if (docLeft >= docWidth / 2) {
        // Element is on the right side: place card to the left
        computedDocLeft = docLeft - cardWidth - gap;
        computedDocTop = docTop + 8;
      } else {
        // Element is on the left side: place card to the right
        computedDocLeft = docLeft + vRect.width + gap;
        computedDocTop = docTop + 8;
      }
    } else {
      // Place below element by default
      computedDocTop = docTop + vRect.height + gap;
      computedDocLeft = docLeft + (vRect.width - cardWidth) / 2;

      // If placing below exceeds document bottom, place above
      const documentHeight = Math.max(
        document.body.scrollHeight,
        document.documentElement.scrollHeight
      );
      if (computedDocTop + cardHeight > documentHeight - 20 && docTop > cardHeight + gap) {
        computedDocTop = docTop - cardHeight - gap;
      }
    }

    // Clamp horizontally within document boundaries
    const maxDocLeft = docWidth - cardWidth - 20;
    computedDocLeft = Math.max(16, Math.min(maxDocLeft, computedDocLeft));
    computedDocTop = Math.max(16, computedDocTop);

    setCardCoords({
      left: computedDocLeft,
      top: computedDocTop,
    });
  }, [isActive, currentStep.route, currentStep.selector, pathname]);

  // Handle Step Transition: route navigation, data population, and smooth auto-scrolling
  // STRICTLY fires only when isActive, currentStepIndex, or pathname changes.
  useEffect(() => {
    if (!isActive) {
      hasScrolledStepRef.current = null;
      return;
    }

    if (currentStep.route !== pathname) {
      router.push(currentStep.route);
      return;
    }

    if (pathname === "/estimate") {
      window.dispatchEvent(
        new CustomEvent("estimator:journey-action", {
          detail: { type: "ensure_estimate" },
        })
      );
    }

    let isCancelled = false;
    let attempts = 0;
    const maxAttempts = 30;

    const findAndPosition = () => {
      if (isCancelled) return;
      const el = document.querySelector<HTMLElement>(currentStep.selector);
      if (el) {
        // Auto-scroll ONCE per step with tailored clearance
        if (hasScrolledStepRef.current !== currentStepIndex) {
          hasScrolledStepRef.current = currentStepIndex;
          const vRect = el.getBoundingClientRect();
          if (currentStep.id === "codebase_context") {
            // Scroll down a bit so Codebase context and card below have comfortable visibility
            const currentScrollY = window.pageYOffset || document.documentElement.scrollTop;
            const targetScrollY = currentScrollY + vRect.top - 120;
            window.scrollTo({
              top: Math.max(0, targetScrollY),
              behavior: "smooth",
            });
          } else {
            const isComfortablyInView = vRect.top >= 80 && vRect.bottom <= window.innerHeight - 250;
            if (!isComfortablyInView) {
              el.scrollIntoView({ behavior: "smooth", block: "center" });
            }
          }
        }

        // Position card and highlight in document coordinates
        positionCardAndHighlight();

        // Update viewport cutout once scroll finishes smoothly
        setTimeout(() => {
          if (!isCancelled) {
            const freshEl = document.querySelector<HTMLElement>(currentStep.selector);
            if (freshEl) {
              setTargetViewportRect(freshEl.getBoundingClientRect());
            }
          }
        }, 450);
      } else if (attempts < maxAttempts) {
        attempts++;
        setTimeout(findAndPosition, 70);
      }
    };

    const timer = setTimeout(findAndPosition, 60);

    return () => {
      isCancelled = true;
      clearTimeout(timer);
    };
  }, [isActive, currentStepIndex, pathname, currentStep.route, currentStep.selector, router, positionCardAndHighlight]);

  // Window scroll listener: updates ONLY viewport rect for SVG mask hole via requestAnimationFrame
  // ABSOLUTELY NEVER fights or touches user scrolling!
  useEffect(() => {
    if (!isActive) return;

    let rafId: number | null = null;
    const handleScroll = () => {
      if (rafId !== null) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = null;
        const el = document.querySelector<HTMLElement>(currentStep.selector);
        if (el) {
          setTargetViewportRect(el.getBoundingClientRect());
        }
      });
    };

    const handleResize = () => {
      positionCardAndHighlight();
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("resize", handleResize);

    return () => {
      if (rafId !== null) window.cancelAnimationFrame(rafId);
      window.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", handleResize);
    };
  }, [isActive, currentStep.selector, positionCardAndHighlight]);

  // Keyboard Shortcuts: Ctrl/Cmd + T, Arrows, Esc
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "t") {
        e.preventDefault();
        setIsActive((prev) => !prev);
      } else if (e.key === "Escape" && isActive) {
        handleClose();
      } else if (isActive && e.key === "ArrowRight") {
        e.preventDefault();
        handleNext();
      } else if (isActive && e.key === "ArrowLeft") {
        e.preventDefault();
        handlePrev();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isActive, currentStepIndex]);

  const handleClose = () => {
    try {
      localStorage.setItem(TOUR_STORAGE_KEY, "true");
    } catch {}
    setIsActive(false);
  };

  /**
   * Preload the demo estimate BEFORE the tour navigates to /estimate.
   *
   * Without this, the tour arrives on an empty /estimate screen, the
   * `ensure_estimate` journey action starts a 2-5s backend call, and the
   * later tour steps (chart, questions, packages) have no UI to highlight.
   * Loading first means the estimate screen is populated on arrival.
   */
  const ensureEstimateReady = async (): Promise<boolean> => {
    if (readStoredEstimate()) return true;
    setIsPreparingEstimate(true);
    try {
      const loaded = await api.loadScenario("A");
      const scenarioList = await api.scenarios();
      const scenarioA = scenarioList.find((s) => s.id === "A");
      storeEstimate({ estimate: loaded, scenarioTitle: "Fintech payment + PCI" });
      if (scenarioA?.email_text) storePrefillEmail(scenarioA.email_text);
      markStepComplete("scenario_stream");
      return true;
    } catch (err) {
      // Navigate anyway: /estimate has its own fallback (ensure_estimate).
      console.error("Failed to preload the estimate for the tour", err);
      return false;
    } finally {
      setIsPreparingEstimate(false);
    }
  };

  const goToStep = async (index: number) => {
    const target = STEPS[index];
    if (!target) return;
    const leavingForEstimate =
      target.route === "/estimate" && target.route !== pathname;
    if (leavingForEstimate) {
      await ensureEstimateReady();
    }
    setCurrentStepIndex(index);
    if (target.route !== pathname) {
      router.push(target.route);
    }
  };

  const handleNext = () => {
    if (currentStepIndex < STEPS.length - 1) {
      void goToStep(currentStepIndex + 1);
    } else {
      handleClose();
    }
  };

  const handlePrev = () => {
    if (currentStepIndex > 0) {
      void goToStep(currentStepIndex - 1);
    }
  };

  const handleExecuteAction = async () => {
    if (!currentStep.actionButton) return;
    setIsExecutingAction(true);
    try {
      const actionId = currentStep.actionButton.actionId;
      if (actionId === "load_fintech") {
        const loaded = await api.loadScenario("A");
        const scList = await api.scenarios();
        const scA = scList.find((s) => s.id === "A");
        storeEstimate({ estimate: loaded, scenarioTitle: "Fintech payment + PCI" });
        if (scA?.email_text) storePrefillEmail(scA.email_text);
        markStepComplete("scenario_stream");
        router.push("/estimate?from=scenario");
        setCurrentStepIndex(2);
      } else if (actionId === "select_demo_b") {
        const btn = document.querySelector<HTMLButtonElement>(
          '[data-tour="codebase-selector"] button:nth-child(3)'
        );
        if (btn) btn.click();
      } else if (actionId === "answer_question") {
        const yesBtn = document.querySelector<HTMLButtonElement>(
          '[data-tour="questions-section"] button:has-text("Có"), [data-tour="questions-section"] button'
        );
        if (yesBtn) yesBtn.click();
      } else if (actionId === "run_replay") {
        const btn = document.querySelector<HTMLButtonElement>(
          '[data-tour="proof-replay-panel"] button'
        );
        if (btn) btn.click();
      }
    } catch (err) {
      console.error("Tour action execution failed", err);
    } finally {
      setIsExecutingAction(false);
    }
  };

  return (
    <>
      {/* 1. Floating Launcher in Bottom-Right Corner */}
      {!isActive && (
        <div className="fixed bottom-4 right-4 z-40 no-print font-sans select-none animate-in fade-in duration-200">
          <button
            type="button"
            onClick={() => {
              setIsActive(true);
              if (pathname === "/proof") setCurrentStepIndex(7);
              else if (pathname === "/estimate") setCurrentStepIndex(2);
              else setCurrentStepIndex(0);
            }}
            className="group flex items-center gap-2.5 rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-1)]/95 px-3.5 py-2 text-xs text-[var(--ink)] shadow-[0_12px_32px_rgba(0,0,0,0.85)] backdrop-blur-md transition-all hover:border-[var(--primary)] hover:bg-[var(--surface-2)] hover:shadow-[0_0_20px_rgba(94,106,210,0.3)]"
            title="Interactive Guided Tour (Ctrl/⌘ + T)"
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--primary)] opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-[var(--primary)]"></span>
            </span>
            <IconCompass className="w-3.5 h-3.5 text-[var(--primary)]" />
            <span className="font-medium tracking-tight text-[var(--ink)]">
              Tour hướng dẫn tương tác
            </span>
            <kbd className="hidden sm:inline-block rounded border border-[var(--hairline)] bg-[var(--surface-2)] px-1.5 py-0.5 text-[10px] font-mono text-[var(--ink-tertiary)]">
              ⌘T
            </kbd>
          </button>
        </div>
      )}

      {/* 2. Interactive Spotlight Walkthrough Mode */}
      {isActive && (
        <>
          {/* SVG Cutout Mask (Fixed to viewport so darkening covers entire screen) */}
          <svg
            className="fixed inset-0 h-full w-full pointer-events-none z-[9990] transition-opacity duration-300"
            style={{ pointerEvents: "none" }}
            aria-hidden="true"
          >
            <defs>
              <mask id="tour-spotlight-mask">
                <rect width="100%" height="100%" fill="white" />
                {targetViewportRect && (
                  <rect
                    x={targetViewportRect.left - 2}
                    y={targetViewportRect.top - 2}
                    width={targetViewportRect.width + 4}
                    height={targetViewportRect.height + 4}
                    rx={10}
                    fill="black"
                  />
                )}
              </mask>
            </defs>
            <rect
              width="100%"
              height="100%"
              fill="rgba(1, 1, 2, 0.78)"
              mask="url(#tour-spotlight-mask)"
              style={{ pointerEvents: "none" }}
            />
          </svg>

          {/* Highlight Ring (Absolute in document coordinates: scrolls naturally with page) */}
          {targetDocCoords && (
            <div
              className="absolute pointer-events-none z-[9992] rounded-[10px] border border-[var(--primary)] shadow-[0_0_0_2px_rgba(94,106,210,0.25),0_0_20px_rgba(94,106,210,0.35)] transition-all duration-300 ease-out"
              style={{
                left: `${targetDocCoords.left - 2}px`,
                top: `${targetDocCoords.top - 2}px`,
                width: `${targetDocCoords.width + 4}px`,
                height: `${targetDocCoords.height + 4}px`,
              }}
            >
              {/* Corner Ping Beacon */}
              <span className="absolute -top-1 -right-1 flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#828fff] opacity-75"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-[var(--primary)] border border-white"></span>
              </span>
            </div>
          )}

          {/* Popover Card (Absolute in document coordinates: scrolls naturally with page) */}
          <div
            ref={cardRef}
            className="absolute z-[9999] w-[420px] max-w-[calc(100vw-2rem)] max-h-[85vh] overflow-y-auto rounded-xl border border-[var(--hairline-strong)] bg-[var(--surface-1)] p-4 shadow-[0_24px_64px_rgba(0,0,0,0.96)] backdrop-blur-xl pointer-events-auto transition-all duration-300 ease-out"
            style={{
              left: `${cardCoords.left}px`,
              top: `${cardCoords.top}px`,
            }}
          >
            {/* Header: Step Pill & Close */}
            <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2.5">
              <div className="flex items-center gap-2">
                <span className="rounded bg-[rgba(94,106,210,0.15)] px-2 py-0.5 text-[10px] font-mono font-semibold tracking-wider text-[var(--primary-hover)] border border-[rgba(94,106,210,0.3)]">
                  {currentStep.category}
                </span>
                <span className="text-[11px] text-[var(--ink-tertiary)] font-mono">
                  {currentStepIndex + 1}/{STEPS.length}
                </span>
              </div>
              <button
                type="button"
                onClick={handleClose}
                className="flex items-center gap-1 rounded-md border border-transparent px-2 py-0.5 text-xs text-[var(--ink-tertiary)] hover:border-[var(--hairline)] hover:text-[var(--ink)] cursor-pointer"
                title="Đóng tour (Esc)"
              >
                <IconClose className="w-3.5 h-3.5" />
                <span>Đóng</span>
              </button>
            </div>

            {/* Title & Purpose */}
            <div className="mt-3">
              <h3 className="text-sm font-semibold tracking-tight text-[var(--ink)]">
                {currentStep.title}
              </h3>
              <div className="mt-1.5 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--ink-subtle)]">
                <IconInfo className="w-3.5 h-3.5 shrink-0 text-[var(--ink-tertiary)] mt-0.5" />
                <span>{currentStep.purpose}</span>
              </div>
            </div>

            {/* Guidance Callout */}
            <div className="mt-2.5 rounded-lg border border-[var(--hairline)] bg-[var(--surface-2)] p-2.5">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--primary)]">
                <IconMousePointer className="w-3 h-3 text-[var(--primary)]" />
                <span>Hướng dẫn thao tác</span>
              </div>
              <div className="mt-1 text-xs leading-relaxed text-[var(--ink)]">
                {currentStep.guidance}
              </div>
            </div>

            {/* Core Differentiator Note */}
            <div className="mt-2 rounded border border-[var(--hairline)] bg-[var(--canvas)] px-2.5 py-1.5">
              <div className="flex items-start gap-1.5">
                <IconSparkles className="w-3.5 h-3.5 shrink-0 text-[var(--primary)] mt-0.5" />
                <div className="text-[11px] leading-relaxed text-[var(--ink-muted)]">
                  <span className="font-mono text-[9px] uppercase tracking-wider text-[var(--ink-tertiary)] mr-1">
                    Điểm cốt lõi:
                  </span>
                  {currentStep.ahaMoment}
                </div>
              </div>
            </div>

            {/* Optional 1-Click Action Button */}
            {currentStep.actionButton && (
              <div className="mt-3">
                <button
                  type="button"
                  disabled={isExecutingAction}
                  onClick={handleExecuteAction}
                  className="btn btn-primary w-full justify-center gap-2 py-1.5 text-xs font-medium shadow-[0_0_16px_rgba(94,106,210,0.25)] cursor-pointer"
                >
                  {isExecutingAction ? (
                    <Spinner className="h-3.5 w-3.5" />
                  ) : (
                    <IconZap className="w-3.5 h-3.5 text-white" />
                  )}
                  <span>{currentStep.actionButton.label}</span>
                </button>
              </div>
            )}

            {/* Footer Navigation Bar */}
            <div className="mt-3.5 flex items-center justify-between border-t border-[var(--hairline)] pt-3">
              {/* Step indicator dots */}
              <div className="flex items-center gap-1">
                {STEPS.map((_, idx) => (
                  <button
                    key={idx}
                    type="button"
                    disabled={isPreparingEstimate}
                    onClick={() => void goToStep(idx)}
                    className={`h-1.5 rounded-full transition-all cursor-pointer disabled:cursor-not-allowed disabled:opacity-40 ${
                      idx === currentStepIndex
                        ? "w-4 bg-[var(--primary)]"
                        : "w-1.5 bg-[var(--surface-3)] hover:bg-[var(--ink-tertiary)]"
                    }`}
                    title={`Chuyển tới bước ${idx + 1}`}
                  />
                ))}
              </div>

              {/* Next / Back Buttons */}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={currentStepIndex === 0 || isPreparingEstimate}
                  onClick={handlePrev}
                  className="btn text-xs py-1 px-2.5 gap-1.5 disabled:opacity-40 cursor-pointer"
                >
                  <IconArrowLeft className="w-3 h-3" />
                  <span>Trước</span>
                </button>
                <button
                  type="button"
                  disabled={isPreparingEstimate}
                  onClick={handleNext}
                  className="btn btn-primary text-xs py-1 px-3 gap-1.5 cursor-pointer disabled:cursor-wait disabled:opacity-70"
                >
                  {isPreparingEstimate ? (
                    <>
                      <Spinner className="h-3 w-3" />
                      <span>Đang chuẩn bị estimate…</span>
                    </>
                  ) : (
                    <>
                      <span>
                        {currentStepIndex === STEPS.length - 1 ? "Hoàn thành" : "Tiếp theo"}
                      </span>
                      {currentStepIndex === STEPS.length - 1 ? (
                        <IconCheck className="w-3 h-3" />
                      ) : (
                        <IconArrowRight className="w-3 h-3" />
                      )}
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
