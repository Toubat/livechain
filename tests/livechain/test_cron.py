from unittest.mock import patch

import pytest

from livechain.graph.cron import CronJobScheduler, Exp, Interval, Linear, exp, interval, linear


class TestCronExpressions:
    """Test the different CronExpr implementations."""

    def test_interval(self):
        """Test that Interval correctly calculates the next tick."""
        with patch("livechain.graph.cron.now", return_value=100.0):
            interval_expr = Interval(seconds=30)
            assert interval_expr.next_tick() == 130.0

    def test_linear(self):
        """Test that Linear correctly calculates next ticks with increasing intervals."""
        with patch("livechain.graph.cron.now", return_value=100.0):
            linear_expr = Linear(base_seconds=10, step_seconds=5, max_interval_seconds=30)

            # First call: base + (step * 0) = 10 + 0 = 10
            assert linear_expr.next_tick() == 110.0

            # Second call: base + (step * 1) = 10 + 5 = 15
            assert linear_expr.next_tick() == 115.0

            # Third call: base + (step * 2) = 10 + 10 = 20
            assert linear_expr.next_tick() == 120.0

            # Let's skip to where we hit the max
            linear_expr._count = 5  # base + (step * 5) = 10 + 25 = 35 > max(30)
            assert linear_expr.next_tick() == 130.0  # Should use max_interval

    def test_exp(self):
        """Test that Exp correctly calculates next ticks with exponentially increasing intervals."""
        with patch("livechain.graph.cron.now", return_value=100.0):
            exp_expr = Exp(base_seconds=2, exponent=2, max_interval_seconds=20)

            # First call: base * (exponent ** 0) = 2 * 1 = 2
            assert exp_expr.next_tick() == 102.0

            # Second call: base * (exponent ** 1) = 2 * 2 = 4
            assert exp_expr.next_tick() == 104.0

            # Third call: base * (exponent ** 2) = 2 * 4 = 8
            assert exp_expr.next_tick() == 108.0

            # Fourth call: base * (exponent ** 3) = 2 * 8 = 16
            assert exp_expr.next_tick() == 116.0

            # Fifth call: base * (exponent ** 4) = 2 * 16 = 32 > max(20)
            assert exp_expr.next_tick() == 120.0  # Should use max_interval

    def test_helper_functions(self):
        """Test the helper functions for creating cron expressions."""
        assert isinstance(interval(30), Interval)
        assert isinstance(linear(10, 5, 30), Linear)
        assert isinstance(exp(2, 2, 20), Exp)


class TestCronJobScheduler:
    """Test the CronJobScheduler class."""

    @pytest.mark.asyncio
    async def test_scheduler_no_jobs(self):
        """Test that scheduler with no jobs does nothing."""
        scheduler = CronJobScheduler(cron_jobs={})
        async for _job in scheduler.schedule():
            raise AssertionError()

    @pytest.mark.asyncio
    async def test_scheduler_basic_intervals(self):
        """Test that scheduler with mock sleep that advances time."""
        # Control time with a mutable variable
        current_time = 100.0

        def mock_time():
            nonlocal current_time
            return current_time

        async def mock_sleep(seconds):
            nonlocal current_time
            # Advance time when sleep is called
            current_time += seconds

        with (
            patch("livechain.graph.cron.now", side_effect=mock_time),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            # Create scheduler with two jobs with different intervals
            scheduler = CronJobScheduler(
                cron_jobs={
                    "job1": Interval(seconds=15),  # Next tick at 115
                    "job2": Interval(seconds=25),  # Next tick at 125
                }
            )

            # Run the scheduler
            results = []

            i = 0
            async for job in scheduler.schedule():
                results.append((job, current_time))
                i += 1
                if i >= 5:
                    break

            # Verify jobs were executed at expected times
            assert results == [
                ("job1", 115.0),  # job1 first tick
                ("job2", 125.0),  # job2 first tick
                ("job1", 130.0),  # job1 second tick
                ("job1", 145.0),  # job1 third tick
                ("job2", 150.0),  # job2 fourth tick
            ]

    @pytest.mark.asyncio
    async def test_scheduler_with_same_intervals(self):
        """Test scheduler with multiple jobs that have the same interval."""
        current_time = 100.0

        def mock_time():
            nonlocal current_time
            return current_time

        async def mock_sleep(seconds):
            nonlocal current_time
            current_time += seconds

        with (
            patch("livechain.graph.cron.now", side_effect=mock_time),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            # Create scheduler with jobs having identical intervals
            scheduler = CronJobScheduler(
                cron_jobs={
                    "job1": Interval(seconds=20),  # Next tick at 120
                    "job2": Interval(seconds=20),  # Next tick at 120
                }
            )

            # Run the scheduler
            results = []
            i = 0
            async for job in scheduler.schedule():
                results.append((job, current_time))
                i += 1
                if i >= 4:
                    break

            # Jobs with same interval should alternate in their execution
            # But the initial order depends on heap insertion order
            assert len(results) == 4

            # Both jobs should run at the same timestamps
            assert results[0][1] == 120.0
            assert results[1][1] == 120.0
            assert results[2][1] == 140.0
            assert results[3][1] == 140.0

            # Check that both jobs executed twice
            assert results[0][0] != results[1][0]
            assert results[2][0] != results[3][0]
            assert {results[0][0], results[1][0]} == {"job1", "job2"}
            assert {results[2][0], results[3][0]} == {"job1", "job2"}

    @pytest.mark.asyncio
    async def test_scheduler_with_linear_cron(self):
        """Test scheduler with Linear cron expressions."""
        current_time = 100.0

        def mock_time():
            nonlocal current_time
            return current_time

        async def mock_sleep(seconds):
            nonlocal current_time
            current_time += seconds

        with (
            patch("livechain.graph.cron.now", side_effect=mock_time),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            # Create scheduler with a Linear cron expression
            # base=5, step=5, max=20
            # Intervals: 5, 10, 15, 20, 20, ...
            scheduler = CronJobScheduler(
                cron_jobs={
                    "linear_job": Linear(base_seconds=5, step_seconds=5, max_interval_seconds=20),
                }
            )

            # Run the scheduler
            results = []
            i = 0
            async for job in scheduler.schedule():
                results.append((job, current_time))
                i += 1
                if i >= 5:
                    break

            # Verify jobs were executed at the expected times with increasing intervals
            assert results == [
                ("linear_job", 105.0),  # First tick: base=5
                ("linear_job", 115.0),  # Second tick: base + step = 10
                ("linear_job", 130.0),  # Third tick: base + 2*step = 15
                ("linear_job", 150.0),  # Fourth tick: base + 3*step = 20
                ("linear_job", 170.0),  # Fifth tick: max = 20
            ]

    @pytest.mark.asyncio
    async def test_scheduler_with_exp_cron(self):
        """Test scheduler with Exponential cron expressions."""
        current_time = 100.0

        def mock_time():
            nonlocal current_time
            return current_time

        async def mock_sleep(seconds):
            nonlocal current_time
            current_time += seconds

        with (
            patch("livechain.graph.cron.now", side_effect=mock_time),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            # Create scheduler with an Exp cron expression
            # base=2, exponent=2, max=20
            # Intervals: 2, 4, 8, 16, 20, 20, ...
            scheduler = CronJobScheduler(
                cron_jobs={
                    "exp_job": Exp(base_seconds=2, exponent=2, max_interval_seconds=20),
                }
            )

            # Run the scheduler
            results = []
            i = 0
            async for job in scheduler.schedule():
                results.append((job, current_time))
                i += 1
                if i >= 5:
                    break

            # Verify jobs were executed at the expected times with exponentially increasing intervals
            assert results == [
                ("exp_job", 102.0),  # First tick: base=2
                ("exp_job", 106.0),  # Second tick: base * exponent^1 = 4
                ("exp_job", 114.0),  # Third tick: base * exponent^2 = 8
                ("exp_job", 130.0),  # Fourth tick: base * exponent^3 = 16
                ("exp_job", 150.0),  # Fifth tick: max = 20
            ]

    @pytest.mark.asyncio
    async def test_scheduler_mixed_cron_types(self):
        """Test scheduler with a mix of different cron expression types."""
        current_time = 100.0

        def mock_time():
            nonlocal current_time
            return current_time

        async def mock_sleep(seconds):
            nonlocal current_time
            current_time += seconds

        with (
            patch("livechain.graph.cron.now", side_effect=mock_time),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            # Create scheduler with different types of cron expressions
            scheduler = CronJobScheduler(
                cron_jobs={
                    "interval_job": Interval(seconds=8),
                    "linear_job": Linear(base_seconds=5, step_seconds=5, max_interval_seconds=30),
                    "exp_job": Exp(base_seconds=3, exponent=2, max_interval_seconds=25),
                }
            )

            # Run the scheduler
            results = []
            i = 0
            async for job in scheduler.schedule():
                results.append((job, current_time))
                i += 1
                if i >= 8:
                    break

            # First 6 jobs should be in this order and at these times:
            # interval_job at 108, 116, 124, 132, 140, 148
            # linear_job at 105, 115, 130
            # exp_job at 103, 109, 121, 125, 125
            assert results == [
                ("exp_job", 103.0),
                ("linear_job", 105.0),
                ("interval_job", 108.0),
                ("exp_job", 109.0),
                ("linear_job", 115.0),
                ("interval_job", 116.0),
                ("exp_job", 121.0),
                ("interval_job", 124.0),
            ]


if __name__ == "__main__":
    pytest.main()
