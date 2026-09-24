package app.myvitals.ui.strength

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** UI-F4: the hero's weight steppers walk the server's load ladder. */
class NextWeightTest {
    private val ladder = listOf(30.0, 31.0, 31.5, 32.5, 33.0, 35.0)

    @Test fun walksToTheNextRealRung() {
        assertEquals(33.0, nextWeight("32.5", null, ladder, up = true))
        assertEquals(31.5, nextWeight("32.5", null, ladder, up = false))
    }

    @Test fun typedOffLadderValueStepsToTheNearestRungInThatDirection() {
        assertEquals(33.0, nextWeight("32.7", null, ladder, up = true))
        assertEquals(32.5, nextWeight("32.7", null, ladder, up = false))
    }

    @Test fun blankFieldStartsFromTheTarget() {
        assertEquals(35.0, nextWeight("", 33.0, ladder, up = true))
    }

    @Test fun ladderEdgesReturnNullRatherThanInventingALoad() {
        assertNull(nextWeight("35", null, ladder, up = true))
        assertNull(nextWeight("30", null, ladder, up = false))
    }

    @Test fun olderServerFallsBackToTwoAndAHalf() {
        assertEquals(35.0, nextWeight("32.5", null, null, up = true))
        assertEquals(0.0, nextWeight("1", null, null, up = false))
    }
}
